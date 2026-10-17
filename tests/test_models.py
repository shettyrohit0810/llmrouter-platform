"""Integration tests for the Milestone 4 schema-only ORM models -- require
the local dev Postgres container (JSONB/UUID are Postgres-specific dialect
types, so these can't be tested against in-memory SQLite the way
tests/backend/test_db.py's generic BaseRepository test is). No
service/repository/endpoint code exists for these tables yet (that's later
milestones) -- these tests exist to prove the ORM mappings themselves are
correct: round-tripping through the real database, including the
metadata -> metadata_ Python-attribute rename these models rely on.
"""

import uuid

import pytest

from backend.api.rbac import service as rbac_service
from backend.api.repositories.user_repository import UserRepository
from backend.config import BackendConfig
from backend.db.models.audit import AuditLog
from backend.db.models.experiments import Experiment
from backend.db.models.jobs import BenchmarkResult, JobRecord, TrainingJobDetail
from backend.db.models.registry import Model, Router, RouterVersion
from backend.db.models.usage import UsageRecord
from backend.db.session import init_engine, session_scope


@pytest.fixture(autouse=True, scope="module")
def _ensure_engine():
    # Lets this file run standalone (`pytest tests/backend/test_models.py`)
    # without depending on another test module having already called
    # create_app() -> init_engine() first. Idempotent, so harmless when the
    # engine is already initialized by an earlier test in a full-suite run.
    init_engine(BackendConfig.from_env().database_url)


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


def _make_user_and_project(db):
    user = UserRepository(db).create(email=_unique_email(), is_active=True, is_email_verified=True)
    db.flush()
    org = rbac_service.create_organization(db, owner=user, name=f"Org {uuid.uuid4().hex[:8]}")
    project = rbac_service.create_project(db, organization_id=org.id, name="Default")
    db.flush()
    return user, project


@pytest.mark.integration
def test_job_record_roundtrip():
    with session_scope() as db:
        user, project = _make_user_and_project(db)
        job = JobRecord(
            project_id=project.id,
            job_type="train",
            status="queued",
            created_by=user.id,
        )
        db.add(job)
        db.flush()
        job_id = job.id

    with session_scope() as db:
        fetched = db.get(JobRecord, job_id)
        assert fetched is not None
        assert fetched.job_type == "train"
        assert fetched.status == "queued"
        assert fetched.retry_count == 0


@pytest.mark.integration
def test_training_job_detail_one_to_one_with_job():
    with session_scope() as db:
        _, project = _make_user_and_project(db)
        job = JobRecord(project_id=project.id, job_type="train", status="completed")
        db.add(job)
        db.flush()
        detail = TrainingJobDetail(
            job_id=job.id,
            router_name="knnrouter",
            config_path="configs/train/knnrouter.yaml",
            device="cpu",
        )
        db.add(detail)
        db.flush()
        job_id = job.id

    with session_scope() as db:
        fetched = db.query(TrainingJobDetail).filter(TrainingJobDetail.job_id == job_id).first()
        assert fetched is not None
        assert fetched.router_name == "knnrouter"


@pytest.mark.integration
def test_benchmark_result_roundtrip():
    with session_scope() as db:
        _, project = _make_user_and_project(db)
        job = JobRecord(project_id=project.id, job_type="benchmark", status="completed")
        db.add(job)
        db.flush()
        result = BenchmarkResult(
            job_id=job.id,
            router="knnrouter",
            dataset="default",
            num_queries=50,
            accuracy=0.42,
            average_latency_seconds=1.1,
            average_token_usage=340.5,
            routing_distribution={"small-model": 30, "large-model": 20},
            failures=0,
            evaluation_summary="ok",
        )
        db.add(result)
        db.flush()
        job_id = job.id

    with session_scope() as db:
        fetched = db.query(BenchmarkResult).filter(BenchmarkResult.job_id == job_id).first()
        assert fetched is not None
        assert fetched.accuracy == 0.42
        assert fetched.routing_distribution == {"small-model": 30, "large-model": 20}


@pytest.mark.integration
def test_experiment_metadata_column_roundtrip():
    """The Python attribute is `metadata_` (mapped to the DB column
    "metadata") because `metadata` is reserved by DeclarativeBase -- this
    test is the regression check that the rename actually works end-to-end,
    not just that the model class can be imported."""
    with session_scope() as db:
        user, project = _make_user_and_project(db)
        experiment = Experiment(
            project_id=project.id,
            experiment_type="train",
            router_name="knnrouter",
            metrics={"accuracy": 0.9},
            metadata_={"note": "manual test"},
            created_by=user.id,
        )
        db.add(experiment)
        db.flush()
        experiment_id = experiment.id

    with session_scope() as db:
        fetched = db.get(Experiment, experiment_id)
        assert fetched is not None
        assert fetched.metadata_ == {"note": "manual test"}
        assert fetched.metrics == {"accuracy": 0.9}


@pytest.mark.integration
def test_router_and_router_version_roundtrip():
    with session_scope() as db:
        router = Router(
            name=f"testrouter-{uuid.uuid4().hex[:8]}",
            class_name="TestRouter",
            trainable=True,
            status="active",
            tags=["experimental"],
        )
        db.add(router)
        db.flush()
        version = RouterVersion(
            router_id=router.id,
            version_label="v1",
            checkpoint_path="saved_models/testrouter/v1.pkl",
            metadata_={"trained_on": "default"},
            status="active",
        )
        db.add(version)
        db.flush()
        router_id, version_id = router.id, version.id

    with session_scope() as db:
        fetched_router = db.get(Router, router_id)
        fetched_version = db.get(RouterVersion, version_id)
        assert fetched_router is not None
        assert fetched_version is not None
        assert fetched_version.router_id == router_id
        assert fetched_version.metadata_ == {"trained_on": "default"}


@pytest.mark.integration
def test_model_registry_entry_roundtrip():
    with session_scope() as db:
        model = Model(
            name=f"test-model-{uuid.uuid4().hex[:8]}",
            provider="sample",
            context_limit=128000,
            input_price=0.2,
            output_price=0.2,
            tags=["fast"],
        )
        db.add(model)
        db.flush()
        model_id = model.id

    with session_scope() as db:
        fetched = db.get(Model, model_id)
        assert fetched is not None
        assert fetched.provider == "sample"
        assert fetched.tags == ["fast"]


@pytest.mark.integration
def test_audit_log_roundtrip():
    with session_scope() as db:
        user, project = _make_user_and_project(db)
        log = AuditLog(
            project_id=project.id,
            user_id=user.id,
            action="job.train.start",
            resource_type="job",
            resource_id=str(uuid.uuid4()),
            metadata_={"router": "knnrouter"},
            ip_address="127.0.0.1",
        )
        db.add(log)
        db.flush()
        log_id = log.id

    with session_scope() as db:
        fetched = db.get(AuditLog, log_id)
        assert fetched is not None
        assert fetched.action == "job.train.start"
        assert fetched.metadata_ == {"router": "knnrouter"}


@pytest.mark.integration
def test_usage_record_roundtrip():
    with session_scope() as db:
        user, project = _make_user_and_project(db)
        record = UsageRecord(
            organization_id=project.organization_id,
            project_id=project.id,
            user_id=user.id,
            endpoint="/api/v1/route",
            router_name="knnrouter",
            model_name="small-model",
            latency_ms=42.5,
            tokens_input=10,
            tokens_output=20,
            status_code=200,
        )
        db.add(record)
        db.flush()
        record_id = record.id

    with session_scope() as db:
        fetched = db.get(UsageRecord, record_id)
        assert fetched is not None
        assert fetched.endpoint == "/api/v1/route"
        assert fetched.status_code == 200

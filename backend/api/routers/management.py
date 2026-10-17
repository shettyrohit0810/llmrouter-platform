"""Management API endpoints -- every handler here is a thin wrapper calling
existing llmrouter functions. No routing, training, or evaluation logic is
implemented in this module."""

import logging
import time
import uuid
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.auth import service as auth_service
from backend.api.auth.dependencies import get_backend_config, get_current_user
from backend.api.auth.exceptions import AuthError
from backend.api.dependencies.project_context import ProjectContext, get_optional_project_context
from backend.api.rbac import service as rbac_service
from backend.api.rbac.roles import Role, meets_minimum
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    ProjectRepository,
)
from backend.api.schemas.benchmark import (
    BenchmarkCompareRequest,
    BenchmarkRequest,
    BenchmarkResponse,
)
from backend.api.schemas.inference import InferRequest, InferResponse, RouteRequest, RouteResponse
from backend.api.schemas.jobs import JobListResponse, JobResponse
from backend.api.schemas.routers import ModelListResponse, RouterListResponse
from backend.api.schemas.training import TrainAcceptedResponse, TrainRequest
from backend.api.services import audit, experiments, router_registry, usage
from backend.api.services.config_resolver import resolve_config
from backend.api.services.jobs import get_job_manager
from backend.config import BackendConfig
from backend.db.models.user import User
from backend.db.session import get_db

logger = logging.getLogger("backend.management")

router = APIRouter(tags=["management"])


def _record_usage_safe(
    db: Session,
    project_context: Optional[ProjectContext],
    *,
    endpoint: str,
    router_name: Optional[str] = None,
    model_name: Optional[str] = None,
    latency_ms: float,
    tokens_input: Optional[int] = None,
    tokens_output: Optional[int] = None,
    status_code: int = 200,
) -> None:
    """Usage tracking is auxiliary bookkeeping, same as experiment/registry
    creation -- a failure here must never affect the actual request/job
    outcome. Only records when a project context resolved (API-key call
    whose key has a project); see backend/api/services/usage.py."""
    if project_context is None:
        return
    try:
        usage.record_usage(
            db,
            organization_id=project_context.organization_id,
            project_id=project_context.project_id,
            api_key_id=project_context.api_key_id,
            user_id=project_context.user_id,
            endpoint=endpoint,
            router_name=router_name,
            model_name=model_name,
            latency_ms=latency_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            status_code=status_code,
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to record usage for %s", endpoint)


def _release_connection(db: Session) -> None:
    """End the request session's transaction so its connection returns to the pool.

    Handlers resolve the caller's project context through the request session
    (a read), then do slow work or open another session (enqueueing a job).
    Without this, every in-flight request pins one pooled connection while
    waiting for a second one, and a burst of concurrent requests can exhaust
    the pool with all of them waiting on each other. The session reconnects
    automatically on its next use (audit/usage writes)."""
    db.commit()


def _job_owner(project_context: Optional[ProjectContext]) -> Dict[str, Any]:
    """Who a job belongs to, recorded on the jobs row so read access can be
    enforced later (anonymous jobs have no owner)."""
    if project_context is None:
        return {}
    return {"project_id": project_context.project_id, "created_by": project_context.user_id}


def _job_payload(
    request: Union[TrainRequest, BenchmarkRequest, BenchmarkCompareRequest],
    project_context: Optional[ProjectContext],
) -> Dict[str, Any]:
    """Serializes the request plus project-context ids into the plain dict
    backend/worker/runner.py reconstructs the job from -- the worker runs in
    a separate process from this one, so nothing here can be a closure over
    live Python objects the way the old BackgroundTasks-based _run()
    functions were."""
    payload: Dict[str, Any] = request.model_dump()
    payload.update(
        {
            "project_id": str(project_context.project_id) if project_context else None,
            "organization_id": str(project_context.organization_id) if project_context else None,
            "api_key_id": str(project_context.api_key_id) if project_context else None,
            "user_id": (
                str(project_context.user_id)
                if project_context and project_context.user_id
                else None
            ),
        }
    )
    return payload


@router.get("/routers", response_model=RouterListResponse)
async def get_routers():
    return RouterListResponse(routers=router_registry.list_routers())


@router.get("/models", response_model=ModelListResponse)
async def get_models(
    llm_data_path: str = Query(
        "data/sample/llm_candidates.json",
        description="Path to the LLM candidates JSON file",
    ),
):
    return ModelListResponse(models=router_registry.list_models(llm_data_path))


@router.post("/route", response_model=RouteResponse)
def route(
    request: RouteRequest,
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    db: Session = Depends(get_db),
):
    from llmrouter.cli.router_inference import load_router, route_query

    _release_connection(db)
    start = time.time()
    router_instance = load_router(request.router, resolve_config(request.config_path))
    result = route_query(request.query, router_instance, request.router)
    duration = time.time() - start

    _record_usage_safe(
        db,
        project_context,
        endpoint="/api/v1/route",
        router_name=request.router,
        model_name=result.get("model_name"),
        latency_ms=duration * 1000,
    )

    return RouteResponse(**{k: v for k, v in result.items() if k in RouteResponse.model_fields})


@router.post("/infer", response_model=InferResponse)
def infer(
    request: InferRequest,
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    db: Session = Depends(get_db),
):
    from llmrouter.cli.router_inference import infer_query, load_router

    _release_connection(db)
    start = time.time()
    router_instance = load_router(request.router, resolve_config(request.config_path))
    result = infer_query(
        request.query,
        router_instance,
        request.router,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    duration = time.time() - start

    experiment_id = None
    if request.create_experiment and project_context is not None:
        # Experiment tracking is auxiliary bookkeeping -- a failure here must
        # never turn a successful inference call into an error response.
        try:
            experiment = experiments.create_experiment(
                db,
                project_id=project_context.project_id,
                job_id=None,
                experiment_type="infer",
                router_name=request.router,
                metrics={"success": result.get("success", False)},
                metadata={"temperature": request.temperature, "max_tokens": request.max_tokens},
                duration_seconds=duration,
                created_by=project_context.user_id,
            )
            experiment_id = experiment.id
        except Exception:
            # Roll back the failed flush -- `db` is the same request-scoped
            # session `_record_usage_safe()` below (and get_db()'s own
            # commit-on-teardown) still need to use; an unrolled-back
            # PendingRollbackError here would otherwise surface as a 500 at
            # response-commit time despite the request itself succeeding.
            db.rollback()
            logger.exception("Failed to create experiment record for infer call")

    _record_usage_safe(
        db,
        project_context,
        endpoint="/api/v1/infer",
        router_name=request.router,
        model_name=result.get("model_name"),
        latency_ms=duration * 1000,
        # No token metering wired into infer_query()'s underlying LLM call
        # path yet -- honest None rather than a fabricated estimate.
        tokens_input=None,
        tokens_output=None,
        # infer_query() itself never raises on a failed LLM call -- a
        # failure surfaces as result["success"]=False with HTTP 200 (an
        # expected, handled outcome per Phase 3's design), so the HTTP
        # status really is always 200 here.
        status_code=200,
    )

    return InferResponse(
        **{k: v for k, v in result.items() if k in InferResponse.model_fields},
        experiment_id=experiment_id,
    )


@router.post("/train", response_model=TrainAcceptedResponse, status_code=202)
def train(
    request: TrainRequest,
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    db: Session = Depends(get_db),
):
    payload = _job_payload(request, project_context)
    _release_connection(db)
    manager = get_job_manager()
    job = manager.submit("train", payload=payload, **_job_owner(project_context))
    if project_context is not None:
        audit.record_event(
            db,
            action="job.train_submitted",
            user_id=project_context.user_id,
            organization_id=project_context.organization_id,
            project_id=project_context.project_id,
            api_key_id=project_context.api_key_id,
            resource_type="job",
            resource_id=job.job_id,
            metadata={"router": request.router, "config_path": request.config_path},
        )
    return TrainAcceptedResponse(job_id=job.job_id)


@router.post("/benchmark", response_model=BenchmarkResponse, status_code=202)
def benchmark(
    request: BenchmarkRequest,
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    db: Session = Depends(get_db),
):
    payload = _job_payload(request, project_context)
    _release_connection(db)
    manager = get_job_manager()
    job = manager.submit("benchmark", payload=payload, **_job_owner(project_context))
    if project_context is not None:
        audit.record_event(
            db,
            action="job.benchmark_submitted",
            user_id=project_context.user_id,
            organization_id=project_context.organization_id,
            project_id=project_context.project_id,
            api_key_id=project_context.api_key_id,
            resource_type="job",
            resource_id=job.job_id,
            metadata={"router": request.router, "dataset": request.dataset},
        )
    return BenchmarkResponse(job_id=job.job_id)


@router.post("/benchmark/compare", response_model=BenchmarkResponse, status_code=202)
def benchmark_compare(
    request: BenchmarkCompareRequest,
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    db: Session = Depends(get_db),
):
    payload = _job_payload(request, project_context)
    _release_connection(db)
    manager = get_job_manager()
    job = manager.submit("benchmark_compare", payload=payload, **_job_owner(project_context))
    if project_context is not None:
        audit.record_event(
            db,
            action="job.benchmark_compare_submitted",
            user_id=project_context.user_id,
            organization_id=project_context.organization_id,
            project_id=project_context.project_id,
            api_key_id=project_context.api_key_id,
            resource_type="job",
            resource_id=job.job_id,
            metadata={"routers": request.routers, "dataset": request.dataset},
        )
    return BenchmarkResponse(job_id=job.job_id)


def _job_to_response(db: Session, job) -> JobResponse:
    experiment = experiments.get_experiment_for_job(db, uuid.UUID(job.job_id))
    return JobResponse(**job.to_dict(), experiment_id=experiment.id if experiment else None)


def _authorize_job_read(
    db: Session,
    job,
    *,
    authorization: Optional[str],
    project_context: Optional[ProjectContext],
    config: BackendConfig,
) -> None:
    """Anonymous jobs (no project) stay readable by id -- the unguessable UUID
    is the capability, as before. A project's jobs require either an API key
    scoped to that project or a user with at least Viewer in its organization."""
    if job.project_id is None:
        return
    project_id = uuid.UUID(job.project_id)
    if project_context is not None and project_context.project_id == project_id:
        return
    if not authorization and project_context is None:
        raise HTTPException(status_code=401, detail="Authentication required for this job")
    if authorization and authorization.lower().startswith("bearer "):
        try:
            user = auth_service.get_user_from_access_token(
                db, config, token=authorization[len("Bearer ") :]
            )
        except AuthError:
            raise HTTPException(status_code=401, detail="Invalid or expired access token")
        project = ProjectRepository(db).get(project_id)
        membership = (
            OrganizationMemberRepository(db).get_membership(project.organization_id, user.id)
            if project is not None
            else None
        )
        if membership is not None and meets_minimum(Role(membership.role), Role.VIEWER):
            return
    raise HTTPException(status_code=403, detail="Not allowed to view this job")


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    authorization: Optional[str] = Header(None),
    project_context: Optional[ProjectContext] = Depends(get_optional_project_context),
    config: BackendConfig = Depends(get_backend_config),
    db: Session = Depends(get_db),
):
    manager = get_job_manager()
    job = manager.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    _authorize_job_read(
        db, job, authorization=authorization, project_context=project_context, config=config
    )
    return _job_to_response(db, job)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Jobs belonging to projects the caller is a member of (any role)."""
    project_ids = [
        project.id
        for org in rbac_service.list_organizations_for_user(db, user=user)
        for project in rbac_service.list_projects(db, organization_id=org.id)
    ]
    manager = get_job_manager()
    jobs = manager.store.list_for_projects(project_ids, limit)
    return JobListResponse(jobs=[_job_to_response(db, j) for j in jobs])

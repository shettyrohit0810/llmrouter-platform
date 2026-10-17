"""Every ORM model module is imported here so importing `backend.db.models`
registers all tables on `backend.db.base.Base.metadata` -- this is what
Alembic's autogenerate and `Base.metadata.create_all()` (tests) rely on.

Later milestones add one `from backend.db.models.<name> import <Model>` line
per model module here, not scattered imports elsewhere.
"""

from backend.db.models.audit import AuditLog
from backend.db.models.experiments import Experiment
from backend.db.models.jobs import BenchmarkResult, JobRecord, TrainingJobDetail
from backend.db.models.organization import Organization, OrganizationMember, Project
from backend.db.models.registry import Model, Router, RouterVersion
from backend.db.models.usage import UsageRecord
from backend.db.models.user import APIKey, OAuthAccount, RefreshToken, User

__all__ = [
    "User",
    "OAuthAccount",
    "RefreshToken",
    "APIKey",
    "Organization",
    "OrganizationMember",
    "Project",
    "JobRecord",
    "TrainingJobDetail",
    "BenchmarkResult",
    "Experiment",
    "Router",
    "RouterVersion",
    "Model",
    "AuditLog",
    "UsageRecord",
]

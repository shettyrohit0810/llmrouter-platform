"""Audit logging: a fire-and-forget record of security-relevant actions
(authentication, API key lifecycle, RBAC/configuration changes, and
training/benchmark job submission).

`record_event()` deliberately shares the caller's request-scoped `db`
rather than opening its own session -- most call sites log a resource
(user, org, project, api key) created moments earlier in that same,
still-uncommitted transaction; a separate session couldn't see that row
yet (READ COMMITTED can't see another transaction's uncommitted insert) and
would fail its own FK constraint. The cost of sharing the session is that a
caller who raises right after logging (auth.login's two failure branches)
must `db.commit()` first, or get_db()'s teardown rolls the whole
transaction -- including the audit row -- back along with the exception;
see auth.py's login() for that pattern.

Like `usage.py` (Milestone 10), `record_event()` itself swallows and logs
any failure rather than requiring every call site to wrap it -- this is
called from four unrelated router modules (auth, api_keys, organizations,
management), and a missed row must never be allowed to turn a successful
register/login/train call into a 500.
"""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.repositories.audit_repository import AuditLogRepository
from backend.db.models.audit import AuditLog

logger = logging.getLogger("backend.audit")


def record_event(
    db: Session,
    *,
    action: str,
    user_id: Optional[UUID] = None,
    organization_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    api_key_id: Optional[UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    try:
        AuditLogRepository(db).create(
            action=action,
            user_id=user_id,
            organization_id=organization_id,
            project_id=project_id,
            api_key_id=api_key_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=metadata,
            ip_address=ip_address,
        )
    except Exception:
        # A failed flush leaves `db` in a state that raises on any further
        # use until rolled back -- roll back just this pending write rather
        # than letting the caller's next `db` operation crash on an
        # unrelated PendingRollbackError.
        db.rollback()
        logger.exception("Failed to record audit event action=%s", action)


def list_audit_logs_for_organization(
    db: Session,
    *,
    organization_id: UUID,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    limit: int = 100,
) -> List[AuditLog]:
    return AuditLogRepository(db).list_for_organization(
        organization_id,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        limit=limit,
    )

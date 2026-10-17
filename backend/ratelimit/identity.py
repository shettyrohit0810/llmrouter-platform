"""Resolves a request to a rate-limit identity: which API key or user made
it (if any), and what plan tier applies. Failure to resolve identity (no
credentials, invalid/expired token) falls back to "anonymous" -- rate
limiting itself never raises an authentication error; that's the actual
auth dependency's job on routes that require it. An anonymous identity
still gets IP-based limiting (backend/ratelimit/plans.py's
ANONYMOUS_IP_LIMIT).
"""

from dataclasses import dataclass

import jwt as pyjwt
from starlette.requests import Request

from backend.api.auth.security import decode_jwt, hash_token
from backend.cache.caches import session_cache
from backend.config import BackendConfig
from backend.db.models.organization import Organization, Project
from backend.db.models.user import APIKey
from backend.db.session import session_scope
from backend.ratelimit.plans import Plan


@dataclass
class RequestIdentity:
    ip: str
    kind: str  # "api_key" | "user" | "anonymous"
    identity_id: str | None
    plan: str


def _client_ip(request: Request) -> str:
    # Behind a real load balancer this would need to trust a specific
    # X-Forwarded-For hop, not the client socket -- out of scope until
    # Milestone 14's deployment guide defines what sits in front of this
    # backend in production.
    return request.client.host if request.client else "unknown"


def _plan_for_api_key(api_key_id: str) -> str:
    cache_key = f"apikey_plan:{api_key_id}"
    cached = session_cache.get(cache_key)
    if cached is not None:
        return cached

    plan = Plan.FREE.value
    with session_scope() as db:
        api_key = db.get(APIKey, api_key_id)
        if api_key is not None and api_key.project_id is not None:
            project = db.get(Project, api_key.project_id)
            if project is not None:
                org = db.get(Organization, project.organization_id)
                if org is not None:
                    plan = org.plan

    session_cache.set(cache_key, plan, ttl_seconds=60)
    return plan


def resolve_identity(request: Request, config: BackendConfig) -> RequestIdentity:
    ip = _client_ip(request)

    api_key_header = request.headers.get("x-api-key")
    if api_key_header:
        # Every field of key_row used below must be read while the session
        # is still open -- accessing an ORM attribute after session_scope()
        # exits raises DetachedInstanceError (a real bug caught here: the
        # revoked/id checks used to live outside this `with` block).
        with session_scope() as db:
            key_row = db.query(APIKey).filter(APIKey.key_hash == hash_token(api_key_header)).first()
            key_id = str(key_row.id) if key_row is not None and not key_row.revoked else None
        if key_id is not None:
            return RequestIdentity(
                ip=ip, kind="api_key", identity_id=key_id, plan=_plan_for_api_key(key_id)
            )

    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("Bearer ") :]
        try:
            payload = decode_jwt(
                token,
                secret_key=config.jwt_secret_key,
                algorithm=config.jwt_algorithm,
                expected_purpose="access",
            )
            # No unambiguous organization for a bare JWT (a user can belong
            # to several, each with a different plan, and Phase 3's original
            # endpoints aren't project-scoped yet) -- default to Free until
            # a project-scoped request can resolve one unambiguously.
            return RequestIdentity(
                ip=ip, kind="user", identity_id=payload["sub"], plan=Plan.FREE.value
            )
        except pyjwt.PyJWTError:
            pass

    return RequestIdentity(ip=ip, kind="anonymous", identity_id=None, plan=Plan.FREE.value)

"""FastAPI dependencies for authenticated routes.

Two independent client types (see docs/migration/phase3_to_phase4.md's
Authentication Model): human users present a JWT bearer token, programmatic
clients present an API key via the X-API-Key header. `get_current_user`
requires a JWT specifically (used by account-management endpoints like API
key creation, where "prove you're logged in as a human" is the point).
`get_current_principal` accepts either (used by Milestone 3's RBAC
middleware and beyond, once it exists) -- kept here now, unused by any route
yet, so Milestone 3 wires it in without re-deriving this logic.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth import service
from backend.api.auth.exceptions import AuthError
from backend.config import BackendConfig
from backend.db.models.user import User
from backend.db.session import get_db


def get_backend_config() -> BackendConfig:
    return BackendConfig.from_env()


def get_current_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Expected 'Authorization: Bearer <token>'")
    token = authorization[len("Bearer ") :]
    try:
        return service.get_user_from_access_token(db, config, token=token)
    except AuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")


def get_current_principal(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
) -> User:
    """Either a JWT bearer token or an X-API-Key header. Not yet used by any
    route (Milestone 3 wires this into the management API's RBAC middleware)."""
    if x_api_key is not None:
        try:
            return service.get_user_from_api_key(db, raw_key=x_api_key)
        except AuthError:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    if authorization is not None:
        return get_current_user(authorization=authorization, db=db, config=config)
    raise HTTPException(status_code=401, detail="Authentication required")

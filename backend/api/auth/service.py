"""Auth business logic: register/login/refresh/logout, password reset, email
verification, API key management. Every function takes a `Session` and the
repositories/services it needs explicitly -- no hidden global state -- and
raises backend.api.auth.exceptions on failure rather than HTTPException,
per that module's docstring.

Access tokens are stateless JWTs (never checked against the database, by
design -- see docs/migration/phase3_to_phase4.md's Authentication Model).
Refresh tokens and API keys are opaque random strings, stored only as a
sha256 hash, so they can be revoked by a DB lookup that an access token
deliberately bypasses for per-request performance.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import jwt as pyjwt
from sqlalchemy.orm import Session

from backend.api.auth.exceptions import (
    APIKeyNotFoundError,
    AccountInactiveError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidOrExpiredTokenError,
)
from backend.api.auth.email import EmailSender
from backend.api.auth.security import (
    create_jwt,
    decode_jwt,
    generate_opaque_token,
    hash_password,
    hash_token,
    refresh_token_expiry,
    verify_password,
)
from backend.api.repositories.user_repository import (
    APIKeyRepository,
    RefreshTokenRepository,
    UserRepository,
)
from backend.config import BackendConfig
from backend.db.models.user import APIKey, User


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _password_fingerprint(user: User) -> str:
    # Embedding a fingerprint of the current password hash in reset tokens
    # makes them single-use without a separate "used tokens" table: once the
    # password changes, the fingerprint in any previously issued token stops
    # matching. See docs/migration/phase3_to_phase4.md's Authentication Model.
    return hash_token(user.hashed_password or "")[:16]


def register(
    db: Session, config: BackendConfig, *, email: str, password: str, full_name: Optional[str]
) -> User:
    users = UserRepository(db)
    if users.get_by_email(email) is not None:
        raise EmailAlreadyRegisteredError(email)
    return users.create(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        is_active=True,
        is_email_verified=False,
    )


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = UserRepository(db).get_by_email(email)
    if user is None or user.hashed_password is None:
        raise InvalidCredentialsError()
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise AccountInactiveError()
    return user


def issue_tokens(db: Session, config: BackendConfig, user: User) -> TokenPair:
    access_token = create_jwt(
        subject=str(user.id),
        secret_key=config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
        ttl_seconds=config.access_token_ttl_minutes * 60,
        purpose="access",
    )
    raw_refresh = generate_opaque_token()
    RefreshTokenRepository(db).create(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=refresh_token_expiry(config.refresh_token_ttl_days),
        revoked=False,
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
    return TokenPair(access_token=access_token, refresh_token=raw_refresh)


def refresh_tokens(db: Session, config: BackendConfig, *, raw_refresh_token: str) -> TokenPair:
    repo = RefreshTokenRepository(db)
    token_row = repo.get_by_hash(hash_token(raw_refresh_token))
    if token_row is None or token_row.revoked:
        raise InvalidOrExpiredTokenError()
    if token_row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise InvalidOrExpiredTokenError()

    user = UserRepository(db).get(token_row.user_id)
    if user is None or not user.is_active:
        raise InvalidOrExpiredTokenError()

    # Rotate: revoke the presented token, issue a brand new pair. Prevents a
    # leaked-but-not-yet-used refresh token from being replayed indefinitely.
    repo.update(token_row, revoked=True)
    return issue_tokens(db, config, user)


def logout(db: Session, *, raw_refresh_token: str) -> Optional[UUID]:
    """Returns the logged-out user's id (for the caller's audit log), or
    None if the token didn't match anything -- an invalid/already-revoked
    refresh token isn't an error (logout is idempotent by design), it just
    has nothing to audit."""
    repo = RefreshTokenRepository(db)
    token_row = repo.get_by_hash(hash_token(raw_refresh_token))
    if token_row is not None and not token_row.revoked:
        repo.update(token_row, revoked=True)
        return token_row.user_id
    return None


def get_user_from_access_token(db: Session, config: BackendConfig, *, token: str) -> User:
    try:
        payload = decode_jwt(
            token,
            secret_key=config.jwt_secret_key,
            algorithm=config.jwt_algorithm,
            expected_purpose="access",
        )
    except pyjwt.PyJWTError:
        raise InvalidOrExpiredTokenError()
    user = UserRepository(db).get(UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise InvalidOrExpiredTokenError()
    return user


def request_password_reset(
    db: Session, config: BackendConfig, email_sender: EmailSender, *, email: str
) -> None:
    """Always succeeds from the caller's perspective (no user-enumeration via
    response differences) -- if the email isn't registered, this is a no-op."""
    user = UserRepository(db).get_by_email(email)
    if user is None:
        return
    token = create_jwt(
        subject=str(user.id),
        secret_key=config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
        ttl_seconds=3600,
        purpose="password_reset",
        extra_claims={"pwd_fp": _password_fingerprint(user)},
    )
    email_sender.send(
        to=user.email,
        subject="Reset your LLMRouter password",
        body=f"Reset token (valid 1 hour): {token}",
    )


def confirm_password_reset(
    db: Session, config: BackendConfig, *, token: str, new_password: str
) -> None:
    try:
        payload = decode_jwt(
            token,
            secret_key=config.jwt_secret_key,
            algorithm=config.jwt_algorithm,
            expected_purpose="password_reset",
        )
    except pyjwt.PyJWTError:
        raise InvalidOrExpiredTokenError()

    users = UserRepository(db)
    user = users.get(UUID(payload["sub"]))
    if user is None:
        raise InvalidOrExpiredTokenError()
    if payload.get("pwd_fp") != _password_fingerprint(user):
        # Password already changed since this token was issued -- token is
        # either stale or already used once. Either way, reject.
        raise InvalidOrExpiredTokenError()
    users.update(user, hashed_password=hash_password(new_password))


def request_email_verification(
    db: Session, config: BackendConfig, email_sender: EmailSender, *, user: User
) -> None:
    token = create_jwt(
        subject=str(user.id),
        secret_key=config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
        ttl_seconds=86400,
        purpose="email_verification",
    )
    email_sender.send(
        to=user.email,
        subject="Verify your LLMRouter email",
        body=f"Verification token (valid 24 hours): {token}",
    )


def confirm_email_verification(db: Session, config: BackendConfig, *, token: str) -> None:
    try:
        payload = decode_jwt(
            token,
            secret_key=config.jwt_secret_key,
            algorithm=config.jwt_algorithm,
            expected_purpose="email_verification",
        )
    except pyjwt.PyJWTError:
        raise InvalidOrExpiredTokenError()
    users = UserRepository(db)
    user = users.get(UUID(payload["sub"]))
    if user is None:
        raise InvalidOrExpiredTokenError()
    if not user.is_email_verified:
        users.update(user, is_email_verified=True)


_API_KEY_PREFIX_VISIBLE_CHARS = 12


def create_api_key(
    db: Session, *, user: User, name: str, project_id: Optional[UUID] = None
) -> tuple[str, APIKey]:
    raw_key = generate_opaque_token(prefix="lr_live_")
    row = APIKeyRepository(db).create(
        created_by=user.id,
        project_id=project_id,
        name=name,
        key_prefix=raw_key[:_API_KEY_PREFIX_VISIBLE_CHARS],
        key_hash=hash_token(raw_key),
        revoked=False,
    )
    return raw_key, row


def list_api_keys(db: Session, *, user: User) -> list[APIKey]:
    return APIKeyRepository(db).list_for_user(user.id)


def revoke_api_key(db: Session, *, user: User, key_id: UUID) -> None:
    repo = APIKeyRepository(db)
    key = repo.get(key_id)
    if key is None or key.created_by != user.id:
        raise APIKeyNotFoundError()
    repo.update(key, revoked=True)


def get_user_from_api_key(db: Session, *, raw_key: str) -> User:
    repo = APIKeyRepository(db)
    key_row = repo.get_by_hash(hash_token(raw_key))
    if key_row is None or key_row.revoked:
        raise InvalidOrExpiredTokenError()
    if key_row.expires_at is not None and key_row.expires_at.replace(
        tzinfo=timezone.utc
    ) < datetime.now(timezone.utc):
        raise InvalidOrExpiredTokenError()
    repo.update(key_row, last_used_at=datetime.now(timezone.utc))
    user = UserRepository(db).get(key_row.created_by)
    if user is None or not user.is_active:
        raise InvalidOrExpiredTokenError()
    return user

"""Password hashing and JWT encode/decode.

Uses `bcrypt` directly rather than passlib -- passlib's bcrypt backend has a
known compatibility gap with bcrypt>=4.1 (its version-detection code expects
an attribute recent bcrypt releases removed), and direct use is simpler for
the one hashing scheme this project needs. Uses PyJWT (not python-jose) for
JWT encode/decode -- more actively maintained, standard choice for FastAPI.
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import bcrypt
import jwt

# bcrypt silently truncates inputs over 72 bytes -- reject longer passwords
# explicitly at hashing time instead of allowing a surprising truncation.
_BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed stored hash -- treat as a verification failure, not a crash.
        return False


def hash_token(raw_token: str) -> str:
    """Refresh tokens and API keys are stored as sha256 hashes, never in
    plaintext -- this is a lookup key, not a password, so a fast hash (no
    salt/work-factor) is correct here; the token itself already has enough
    entropy (see generate_opaque_token)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_opaque_token(prefix: str = "") -> str:
    """A high-entropy random token for refresh tokens / API keys. `prefix`
    (e.g. "lr_live_") makes API keys recognizable in the UI without revealing
    the secret part."""
    return f"{prefix}{secrets.token_urlsafe(32)}"


TokenPurpose = Literal["access", "password_reset", "email_verification"]


def create_jwt(
    *,
    subject: str,
    secret_key: str,
    algorithm: str,
    ttl_seconds: int,
    purpose: TokenPurpose = "access",
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "purpose": purpose,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_jwt(
    token: str, *, secret_key: str, algorithm: str, expected_purpose: Optional[TokenPurpose] = None
) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/
    wrong-purpose token -- callers translate that into a 401, not this
    module, keeping HTTP concerns out of the security primitives."""
    payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    if expected_purpose is not None and payload.get("purpose") != expected_purpose:
        raise jwt.InvalidTokenError(f"Expected token purpose '{expected_purpose}'")
    return payload


def access_token_expiry(ttl_minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)


def refresh_token_expiry(ttl_days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=ttl_days)

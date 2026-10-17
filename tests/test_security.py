"""Unit tests for backend/api/auth/security.py -- no database, no network."""

import jwt as pyjwt
import pytest

from backend.api.auth.security import (
    create_jwt,
    decode_jwt,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_password_rejects_over_72_bytes():
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_verify_password_false_for_malformed_hash():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


def test_generate_opaque_token_has_prefix_and_is_unique():
    a = generate_opaque_token(prefix="lr_live_")
    b = generate_opaque_token(prefix="lr_live_")
    assert a.startswith("lr_live_")
    assert a != b


def test_jwt_roundtrip():
    token = create_jwt(subject="user-123", secret_key="secret", algorithm="HS256", ttl_seconds=60)
    payload = decode_jwt(token, secret_key="secret", algorithm="HS256")
    assert payload["sub"] == "user-123"
    assert payload["purpose"] == "access"


def test_jwt_rejects_wrong_purpose():
    token = create_jwt(
        subject="user-123",
        secret_key="secret",
        algorithm="HS256",
        ttl_seconds=60,
        purpose="password_reset",
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_jwt(token, secret_key="secret", algorithm="HS256", expected_purpose="access")


def test_jwt_rejects_expired_token():
    token = create_jwt(subject="user-123", secret_key="secret", algorithm="HS256", ttl_seconds=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_jwt(token, secret_key="secret", algorithm="HS256")


def test_jwt_rejects_wrong_secret():
    token = create_jwt(subject="user-123", secret_key="secret", algorithm="HS256", ttl_seconds=60)
    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_jwt(token, secret_key="wrong-secret", algorithm="HS256")

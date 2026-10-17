"""Authentication endpoints -- every handler is a thin wrapper over
backend/api/auth/service.py; no business logic lives in this module."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.auth import service
from backend.api.auth.dependencies import get_backend_config, get_current_user
from backend.api.auth.email import get_email_sender
from backend.api.auth.exceptions import (
    AccountInactiveError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidOrExpiredTokenError,
    OAuthProviderNotConfiguredError,
)
from backend.api.auth.oauth import GithubOAuthProvider, GoogleOAuthProvider, OAuthProvider
from backend.api.schemas.auth import (
    EmailVerificationConfirm,
    LoginRequest,
    LogoutRequest,
    OAuthAuthorizationURLResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.api.services import audit
from backend.config import BackendConfig
from backend.db.models.user import User
from backend.db.session import get_db


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


router = APIRouter(prefix="/auth", tags=["auth"])


def _get_oauth_provider(provider_name: str, config: BackendConfig) -> OAuthProvider:
    if provider_name == "google":
        if not (config.google_oauth_client_id and config.google_oauth_client_secret):
            raise OAuthProviderNotConfiguredError(provider_name)
        return GoogleOAuthProvider(
            client_id=config.google_oauth_client_id,
            client_secret=config.google_oauth_client_secret,
            redirect_uri=config.google_oauth_redirect_uri or "",
        )
    if provider_name == "github":
        if not (config.github_oauth_client_id and config.github_oauth_client_secret):
            raise OAuthProviderNotConfiguredError(provider_name)
        return GithubOAuthProvider(
            client_id=config.github_oauth_client_id,
            client_secret=config.github_oauth_client_secret,
            redirect_uri=config.github_oauth_redirect_uri or "",
        )
    raise HTTPException(status_code=404, detail=f"Unknown OAuth provider '{provider_name}'")


@router.post("/register", response_model=UserResponse, status_code=201)
def register(
    request: RegisterRequest,
    req: Request,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        user = service.register(
            db, config, email=request.email, password=request.password, full_name=request.full_name
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail="Email already registered")
    service.request_email_verification(db, config, get_email_sender(), user=user)
    audit.record_event(
        db,
        action="auth.register",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        ip_address=_client_ip(req),
    )
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    req: Request,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        user = service.authenticate(db, email=request.email, password=request.password)
    except InvalidCredentialsError:
        audit.record_event(
            db,
            action="auth.login_failed",
            metadata={"email": request.email, "reason": "invalid_credentials"},
            ip_address=_client_ip(req),
        )
        # Commit before raising: get_db()'s teardown rolls back the whole
        # session on any propagating exception (including this intentional
        # HTTPException), which would otherwise erase the audit row above
        # along with it -- see record_event()'s docstring.
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    except AccountInactiveError:
        audit.record_event(
            db,
            action="auth.login_failed",
            metadata={"email": request.email, "reason": "account_inactive"},
            ip_address=_client_ip(req),
        )
        db.commit()
        raise HTTPException(status_code=403, detail="Account is inactive")
    tokens = service.issue_tokens(db, config, user)
    audit.record_event(
        db,
        action="auth.login",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        ip_address=_client_ip(req),
    )
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: RefreshRequest,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        tokens = service.refresh_tokens(db, config, raw_refresh_token=request.refresh_token)
    except InvalidOrExpiredTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", status_code=204)
def logout(request: LogoutRequest, req: Request, db: Session = Depends(get_db)):
    user_id = service.logout(db, raw_refresh_token=request.refresh_token)
    if user_id is not None:
        audit.record_event(
            db,
            action="auth.logout",
            user_id=user_id,
            resource_type="user",
            resource_id=str(user_id),
            ip_address=_client_ip(req),
        )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password-reset/request", status_code=202)
def password_reset_request(
    request: PasswordResetRequest,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    # Always 202, whether or not the email is registered -- avoids leaking
    # which emails have accounts.
    service.request_password_reset(db, config, get_email_sender(), email=request.email)


@router.post("/password-reset/confirm", status_code=204)
def password_reset_confirm(
    request: PasswordResetConfirm,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        service.confirm_password_reset(
            db, config, token=request.token, new_password=request.new_password
        )
    except InvalidOrExpiredTokenError:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")


@router.post("/email/verify", status_code=204)
def email_verify(
    request: EmailVerificationConfirm,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        service.confirm_email_verification(db, config, token=request.token)
    except InvalidOrExpiredTokenError:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")


@router.post("/email/resend", status_code=202)
def email_resend(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    service.request_email_verification(db, config, get_email_sender(), user=user)


@router.get("/oauth/{provider}/login", response_model=OAuthAuthorizationURLResponse)
def oauth_login(provider: str, config: BackendConfig = Depends(get_backend_config)):
    try:
        oauth_provider = _get_oauth_provider(provider, config)
    except OAuthProviderNotConfiguredError:
        raise HTTPException(
            status_code=501, detail=f"OAuth provider '{provider}' is not configured"
        )
    # Known simplification (Phase 4 tech debt, see completion report): `state`
    # is generated but not persisted/verified server-side, since a short-lived
    # server-side state store would need Redis (Milestone 5, not yet
    # available). CSRF protection for the OAuth flow is deferred accordingly.
    state = secrets.token_urlsafe(16)
    return OAuthAuthorizationURLResponse(
        authorization_url=oauth_provider.authorization_url(state=state)
    )


@router.get("/oauth/{provider}/callback", response_model=TokenResponse)
def oauth_callback(
    provider: str,
    code: str,
    req: Request,
    db: Session = Depends(get_db),
    config: BackendConfig = Depends(get_backend_config),
):
    try:
        oauth_provider = _get_oauth_provider(provider, config)
    except OAuthProviderNotConfiguredError:
        raise HTTPException(
            status_code=501, detail=f"OAuth provider '{provider}' is not configured"
        )

    profile = oauth_provider.exchange_code_for_profile(code=code)

    from backend.api.repositories.user_repository import OAuthAccountRepository, UserRepository

    oauth_repo = OAuthAccountRepository(db)
    existing_link = oauth_repo.get_by_provider_account(
        profile.provider, profile.provider_account_id
    )
    if existing_link is not None:
        user = UserRepository(db).get(existing_link.user_id)
        if user is None:
            # The linked user row is gone (e.g. deleted out-of-band) but the
            # oauth_accounts row survived -- treat as an auth failure rather
            # than crashing on a None user below.
            raise HTTPException(status_code=401, detail="Linked account no longer exists")
    else:
        users = UserRepository(db)
        user = users.get_by_email(profile.email)
        if user is None:
            # OAuth-verified email is trustworthy -- skip the stubbed
            # verification flow for accounts created this way.
            user = users.create(
                email=profile.email,
                hashed_password=None,
                full_name=profile.full_name,
                is_active=True,
                is_email_verified=True,
            )
        oauth_repo.create(
            user_id=user.id,
            provider=profile.provider,
            provider_account_id=profile.provider_account_id,
        )

    tokens = service.issue_tokens(db, config, user)
    audit.record_event(
        db,
        action="auth.login",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        metadata={"provider": provider},
        ip_address=_client_ip(req),
    )
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)

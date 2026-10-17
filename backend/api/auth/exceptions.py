"""Auth-domain exceptions. Raised by backend/api/auth/service.py, translated
to HTTP status codes by backend/api/auth/routes.py -- keeps the service layer
free of FastAPI/HTTP concerns, matching backend/api/auth/security.py's own
policy of raising library/domain exceptions rather than HTTPException."""


class AuthError(Exception):
    """Base class for every auth-domain failure."""


class InvalidCredentialsError(AuthError):
    pass


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidOrExpiredTokenError(AuthError):
    pass


class AccountInactiveError(AuthError):
    pass


class OAuthProviderNotConfiguredError(AuthError):
    pass


class APIKeyNotFoundError(AuthError):
    pass

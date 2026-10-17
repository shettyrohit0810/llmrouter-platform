"""RBAC-domain exceptions. Raised by backend/api/rbac/service.py, translated
to HTTP status codes only in backend/api/routers/organizations.py -- same
split as backend/api/auth/exceptions.py."""


class RBACError(Exception):
    """Base class for every RBAC-domain failure."""


class OrganizationNotFoundError(RBACError):
    pass


class ProjectNotFoundError(RBACError):
    pass


class NotAMemberError(RBACError):
    pass


class InsufficientRoleError(RBACError):
    pass


class UserNotFoundError(RBACError):
    pass


class LastOwnerError(RBACError):
    """Raised when an action would leave an organization with zero owners."""

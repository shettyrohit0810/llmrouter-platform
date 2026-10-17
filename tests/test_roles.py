"""Unit tests for backend/api/rbac/roles.py -- no database."""

from backend.api.rbac.roles import Role, meets_minimum


def test_owner_meets_every_minimum():
    for minimum in Role:
        assert meets_minimum(Role.OWNER, minimum)


def test_viewer_only_meets_viewer_minimum():
    assert meets_minimum(Role.VIEWER, Role.VIEWER)
    assert not meets_minimum(Role.VIEWER, Role.DEVELOPER)
    assert not meets_minimum(Role.VIEWER, Role.ADMIN)
    assert not meets_minimum(Role.VIEWER, Role.OWNER)


def test_hierarchy_ordering():
    assert meets_minimum(Role.ADMIN, Role.DEVELOPER)
    assert meets_minimum(Role.DEVELOPER, Role.VIEWER)
    assert not meets_minimum(Role.DEVELOPER, Role.ADMIN)
    assert not meets_minimum(Role.ADMIN, Role.OWNER)

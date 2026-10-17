"""Role hierarchy: Owner > Admin > Developer > Viewer.

A single linear rank (not a permission-bitmask system) -- the spec's four
roles are hierarchical ("Owner can do everything Admin can, plus more"), not
independent capability sets, so `require_role(min_role)` comparing ranks is
sufficient and avoids a permissions table this platform doesn't need yet.
"""

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


_RANK = {
    Role.VIEWER: 1,
    Role.DEVELOPER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


def meets_minimum(actual: Role, minimum: Role) -> bool:
    return _RANK[actual] >= _RANK[minimum]

"""Rate-limit plan tiers -- consumed by identity-scoped (user/API key/
organization) limiting. IP-based limiting (backend/ratelimit/identity.py)
uses a fixed anti-abuse ceiling instead, since anonymous traffic has no plan.
"""

from dataclasses import dataclass
from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    DEVELOPER = "developer"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class PlanLimit:
    capacity: float  # token bucket burst capacity
    refill_per_second: float  # steady-state requests/second


PLAN_LIMITS: dict[Plan, PlanLimit] = {
    Plan.FREE: PlanLimit(capacity=60, refill_per_second=1),  # ~60 req/min steady state
    Plan.DEVELOPER: PlanLimit(capacity=600, refill_per_second=10),  # ~600 req/min
    Plan.ENTERPRISE: PlanLimit(capacity=6000, refill_per_second=100),  # ~6000 req/min
}

# Anonymous (no resolved identity) requests -- IP-only, sliding window.
ANONYMOUS_IP_LIMIT = 100
ANONYMOUS_IP_WINDOW_SECONDS = 60.0


def plan_limit(plan: str) -> PlanLimit:
    try:
        return PLAN_LIMITS[Plan(plan)]
    except ValueError:
        return PLAN_LIMITS[Plan.FREE]

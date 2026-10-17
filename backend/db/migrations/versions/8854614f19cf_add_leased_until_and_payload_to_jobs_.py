"""add leased_until and payload to jobs, allow dead_letter status

Revision ID: 8854614f19cf
Revises: 1ecfec987a4b
Create Date: 2026-08-06 01:34:46.627356

Adds real-worker-queue support on top of Milestone 7's PostgresJobStore:
`payload` (JSONB) carries the parameters an out-of-process worker needs to
execute a job (router name, config path, project-context ids, etc.) --
previously this lived only in an in-memory Python closure captured by the
request handler, which an out-of-process worker has no access to. `leased_
until` marks a job as actively claimed while in the future; NULL or past
means reclaimable. `dead_letter` is added as a valid terminal status for a
job that exhausted its retry budget (see backend/worker/queue.py) -- distinct
from `cancelled`, which the schema already had but no code path ever sets
(reserved for a future explicit user-cancel action, not exhausted retries).

Rollback notes: downgrade drops both new columns and reverts the status
CHECK constraint to Milestone 4's original five values. Any row already in
`dead_letter` status would then violate the constraint -- this downgrade is
only safe if no job has reached that status, or if such rows are updated to
`failed` first.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8854614f19cf"
down_revision: Union[str, Sequence[str], None] = "1ecfec987a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "jobs", sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("jobs", sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True))
    # NAMING_CONVENTION (backend/db/base.py) renders "ck" as
    # ck_%(table_name)s_%(constraint_name)s -- passing the already-prefixed
    # name here double-prefixes it (ck_jobs_ck_jobs_valid_status). The short
    # suffix "valid_status" is what actually resolves to "ck_jobs_valid_status".
    op.drop_constraint("valid_status", "jobs", type_="check")
    op.create_check_constraint(
        "valid_status",
        "jobs",
        "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'dead_letter')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("valid_status", "jobs", type_="check")
    op.create_check_constraint(
        "valid_status",
        "jobs",
        "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
    )
    op.drop_column("jobs", "leased_until")
    op.drop_column("jobs", "payload")

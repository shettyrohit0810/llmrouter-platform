"""enable pgcrypto extension

Revision ID: 5b8775bf946a
Revises:
Create Date: 2026-07-17 14:28:43.835444

Rollback notes: downgrade drops the extension. Safe as long as no table's
column default still references gen_random_uuid() at downgrade time -- every
later migration that adds such a column must be downgraded first (Alembic
enforces this ordering automatically via the revision chain).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b8775bf946a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() (from pgcrypto) is used as the server-side default for
    # every table's UUID primary key in every migration from here forward.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")

"""workflow_types.schedulable column (A1.1)

Revision ID: c2a4d7e8b3f9
Revises: b8e5d3f1a4c7
Create Date: 2026-05-07 00:00:00.000000

Adds a `schedulable` boolean to workflow_types. Existing types are all
schedulable, so the column ships with `server_default=TRUE` and the six
seeded rows inherit TRUE on upgrade.

Why: AWF-1 (Analyze Data Collection) is human-trigger only — too expensive
and slow to fire from cron. The frontend will hide schedule UI for any
type whose schedulable flag is false.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2a4d7e8b3f9'
down_revision: Union[str, None] = 'b8e5d3f1a4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_types",
        sa.Column(
            "schedulable",
            sa.Boolean(),
            server_default=sa.text("'TRUE'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_types", "schedulable")

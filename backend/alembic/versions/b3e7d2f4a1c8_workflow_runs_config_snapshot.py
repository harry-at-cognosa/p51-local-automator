"""workflow_runs.config_snapshot column

Revision ID: b3e7d2f4a1c8
Revises: a2c4e6b8d0f1
Create Date: 2026-05-05 00:00:00.000000

Adds a JSON column to workflow_runs that captures the user_workflows.config
in effect at run start. Older rows have NULL config_snapshot — there is no
authoritative source for what their config was, and a fabricated value would
be misleading.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e7d2f4a1c8'
down_revision: Union[str, None] = 'a2c4e6b8d0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("config_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "config_snapshot")

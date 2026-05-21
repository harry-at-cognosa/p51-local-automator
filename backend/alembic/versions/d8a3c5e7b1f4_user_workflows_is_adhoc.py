"""user_workflows: add is_adhoc + per-user partial index (Ad-hoc shell)

Revision ID: d8a3c5e7b1f4
Revises: c7f9e2a5b4d8
Create Date: 2026-05-20 00:00:00.000000

Adds the boolean `is_adhoc` flag to user_workflows. Ad-hoc rows are
hidden from the main `/app/workflows` list and from the Schedules UI;
the new "Ad-hoc Workflows" menu is the only surface that touches them.

API guarantees (not enforced at DB level for v1): at most one ad-hoc
row per (user_id, type_id) where deleted = 0. Saves overwrite the
existing row; they never insert a second.

Partial index supports the single hot lookup "fetch this user's
ad-hoc row for type N." It includes is_adhoc in the column list so a
WHERE is_adhoc = false scan on a heavy user_workflows is still
index-friendly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8a3c5e7b1f4"
down_revision: Union[str, None] = "c7f9e2a5b4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_workflows",
        sa.Column(
            "is_adhoc",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_index(
        "ix_user_workflows_user_adhoc_type",
        "user_workflows",
        ["user_id", "is_adhoc", "type_id"],
        unique=False,
        postgresql_where=sa.text("deleted = 0"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_workflows_user_adhoc_type",
        table_name="user_workflows",
    )
    op.drop_column("user_workflows", "is_adhoc")

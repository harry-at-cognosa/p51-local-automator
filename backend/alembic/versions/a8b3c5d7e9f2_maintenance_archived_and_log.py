"""maintenance: workflow_runs.archived + maintenance_log table

Revision ID: a8b3c5d7e9f2
Revises: d3b6f9a2c4e7
Create Date: 2026-05-11 00:00:00.000000

Phase M.1 — schema groundwork for the archive/purge admin sweep.

Adds:
  - workflow_runs.archived BOOLEAN NOT NULL DEFAULT FALSE — soft-hide flag
    for the archive operation. All run-surfacing queries for non-superusers
    will start filtering on archived = false in M.2.
  - maintenance_log table — append-only audit of non-dry-run sweep actions.
    Each row records who, when, what scope, what cutoff, how many rows were
    touched, and (for purge) how many bytes were freed. Dry-runs do not
    write rows here; only commits do.

No existing rows are touched by this migration. The archived column
defaults to FALSE so all current history remains visible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b3c5d7e9f2'
down_revision: Union[str, None] = 'd3b6f9a2c4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "maintenance_log",
        sa.Column(
            "log_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("api_users.user_id", name="fk_maintenance_log_user_id"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "scope_group_id",
            sa.Integer(),
            sa.ForeignKey("api_groups.group_id", name="fk_maintenance_log_group_id"),
            nullable=True,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "workflows_affected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "runs_affected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "steps_affected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "artifacts_affected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("bytes_freed", sa.BigInteger(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_maintenance_log_created_at",
        "maintenance_log",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_maintenance_log_created_at", table_name="maintenance_log")
    op.drop_table("maintenance_log")
    op.drop_column("workflow_runs", "archived")

"""workflow_runs partial unique index — one active run per workflow

Revision ID: f7a9b3d8c1e0
Revises: e6f0d2c9a4b7
Create Date: 2026-05-06 00:00:00.000000

Adds a Postgres partial unique index on workflow_runs(workflow_id)
filtered to active statuses {'pending','running'}. Enforces "one active
run per workflow" at the DB level, with no race window between
concurrent triggers.

Application-level pre-checks in trigger_run and _run_workflow_background
provide friendly 409 / structured-skip behavior for the common case;
this index is the correctness backstop for the pathological race where
two triggers both pass the pre-check before either can insert a row.

The status filter includes 'pending' defensively even though the engine
currently always inserts rows with status='running' (model server_default
is 'pending', so an SQL-direct insert without an explicit status would
land in 'pending' and we want it locked too).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = 'f7a9b3d8c1e0'
down_revision: Union[str, None] = 'e6f0d2c9a4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ix_workflow_runs_one_active_per_workflow"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "workflow_runs",
        ["workflow_id"],
        unique=True,
        postgresql_where=text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="workflow_runs")

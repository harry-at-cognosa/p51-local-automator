"""workflow_steps.stage and workflow_steps.kind columns

Revision ID: e6f0d2c9a4b7
Revises: d5e9c1b8f3a4
Create Date: 2026-05-06 00:00:00.000000

Adds two nullable VARCHAR columns to workflow_steps in preparation for
the AWF-1 agentic engine.

  stage  — one of {ingest, profile, analyze, synthesize, audit, scribe}
           (or NULL for steps from non-agentic workflow types).
  kind   — one of {skill_call, llm_turn, stage_marker} (or NULL for
           non-agentic steps).

Both default to NULL. Existing rows from types 1–6 are unaffected; their
runs continue to write rows with these columns left NULL. The agentic
engine (A3) populates them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f0d2c9a4b7'
down_revision: Union[str, None] = 'd5e9c1b8f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_steps",
        sa.Column("stage", sa.VARCHAR(), nullable=True),
    )
    op.add_column(
        "workflow_steps",
        sa.Column("kind", sa.VARCHAR(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_steps", "kind")
    op.drop_column("workflow_steps", "stage")

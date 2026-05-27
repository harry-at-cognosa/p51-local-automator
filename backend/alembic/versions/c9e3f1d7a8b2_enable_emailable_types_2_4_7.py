"""enable emailable_results for workflow types 2, 4, 7

Revision ID: c9e3f1d7a8b2
Revises: b6d4e2c9f8a7
Create Date: 2026-05-27 00:00:00.000000

Flips workflow_types.emailable_results from FALSE to TRUE for:

  type 2 — Transaction Data Analyzer
  type 4 — SQL Query Runner
  type 7 — Analyze Data Collection (AWF-1)

Types 5 and 6 (Auto-Reply) are deliberately not opted in — their primary
output IS email, so re-emailing that output is redundant.

The artifact-kind registry in backend/services/results_email.py is
updated in lockstep with this migration. Without those entries the
form would show the section but with no checkboxes to pick.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = 'c9e3f1d7a8b2'
down_revision: Union[str, None] = 'b6d4e2c9f8a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text(
            "UPDATE workflow_types SET emailable_results = TRUE "
            "WHERE type_id IN (2, 4, 7)"
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE workflow_types SET emailable_results = FALSE "
            "WHERE type_id IN (2, 4, 7)"
        )
    )

"""seed api_settings defaults for the new Claude model settings

Revision ID: c2a8e4f9b3d1
Revises: a8b3c5d7e2f6
Create Date: 2026-06-17 09:00:00.000000

Seeds default values for the two new string settings introduced when the
hardcoded model literals in llm_service.py and agentic_engine.py were
lifted into the 3-layer settings chain. Idempotent: only inserts rows
that don't already exist.

These keys mirror the SETTING_DEFAULT_FAST_MODEL /
SETTING_DEFAULT_REASONING_MODEL constants in
`backend/services/workflow_engine.py`. Operators can override per-group
via `group_settings` (groupadmin UI at /app/admin/group-settings), and
power users can override per-workflow via JSON edit of
`workflow.config["default_fast_model"]` /
`workflow.config["default_reasoning_model"]` (no UI control in v1).

If for any reason this migration hasn't run, code-level fallbacks in
workflow_engine.py (DEFAULT_FAST_MODEL_FALLBACK /
DEFAULT_REASONING_MODEL_FALLBACK) keep workflows running with the same
values that would have been seeded — the migration just makes the
values visible/editable in the admin UI.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2a8e4f9b3d1"
down_revision: Union[str, None] = "a8b3c5d7e2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, default_value_as_string). Keep aligned with the FALLBACK
# constants in backend/services/workflow_engine.py.
DEFAULTS: list[tuple[str, str]] = [
    ("default_fast_model",      "claude-sonnet-4-6"),
    ("default_reasoning_model", "claude-opus-4-8"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for name, value in DEFAULTS:
        bind.execute(
            sa.text(
                "INSERT INTO api_settings (name, value) "
                "VALUES (:name, :value) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "value": value},
        )


def downgrade() -> None:
    bind = op.get_bind()
    names = [n for n, _ in DEFAULTS]
    bind.execute(
        sa.text("DELETE FROM api_settings WHERE name = ANY(:names)"),
        {"names": names},
    )

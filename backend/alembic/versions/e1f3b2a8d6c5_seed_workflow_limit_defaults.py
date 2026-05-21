"""seed api_settings defaults for the workflow-limits consistency sweep

Revision ID: e1f3b2a8d6c5
Revises: d8a3c5e7b1f4
Create Date: 2026-05-21 00:00:00.000000

Seeds default values into `api_settings` for every numeric workflow
limit lifted into the 3-layer settings chain. Idempotent: only inserts
rows that don't already exist.

These keys mirror the SETTING_* constants in
`backend/services/workflow_engine.py`. Operators can override per-group
via `group_settings` (groupadmin UI at /app/admin/group-settings), and
users can override per-workflow via the config form ("Advanced" section
on each workflow type's form).

Hardcoded absolute ceilings live in code as runaway-cost guards
(ABS_MAX_AGENT_TURNS, ABS_MAX_LLM_TOKENS); api_settings values above
those ceilings are silently clamped at run time.

`sql_row_limit` is intentionally seeded as the empty string (= None
when resolved) so existing Type 4 workflows that return full result
sets continue to do so. Operators who want a hard cap set a numeric
value here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f3b2a8d6c5"
down_revision: Union[str, None] = "d8a3c5e7b1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, default_value_as_string). Empty string = no default (resolver
# falls through to whatever the runner uses as its hardcoded fallback).
DEFAULTS: list[tuple[str, str]] = [
    ("email_fetch_limit",            "100"),
    ("analyzer_timeout_seconds",     "120"),
    ("analyzer_llm_sample_rows",     "50"),
    ("analyzer_text_truncate_chars", "8000"),
    ("sql_llm_sample_rows",          "50"),
    ("sql_row_limit",                ""),
    ("reply_max_candidates",         "20"),
    ("analyze_max_agent_turns",      "25"),
    ("audit_max_agent_turns",        "12"),
    ("llm_max_tokens",               "4096"),
    ("step_summary_truncate_chars",  "2000"),
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

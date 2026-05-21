"""type 7 config_schema: add Advanced numeric limit knobs

Revision ID: f4c8d2e9a3b6
Revises: e1f3b2a8d6c5
Create Date: 2026-05-21 00:00:00.000000

Extends Type 7's `config_schema` with four new number fields for the
agentic-engine knobs lifted in WL.2:

  - analyze_max_agent_turns
  - audit_max_agent_turns
  - llm_max_tokens
  - step_summary_truncate_chars

All four are optional per-workflow overrides. Blank values flow through
the 3-layer chain (group_settings → api_settings → runner fallback).
The runner clamps any resolved value above the hardcoded ABS_MAX_*
ceilings at run time, so an end-user can't override into runaway-cost
territory regardless of what they type here.

Idempotent: only inserts fields that don't already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "f4c8d2e9a3b6"
down_revision: Union[str, None] = "e1f3b2a8d6c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_FIELDS = [
    {
        "name": "analyze_max_agent_turns",
        "label": "Analyze stage — max agent turns",
        "label_suffix": "(advanced)",
        "type": "number",
        "width": "third",
        "min": 1,
        "max": 100,
        "placeholder": "Default: 25",
        "help": (
            "Maximum tool-using LLM iterations in the analyze stage. "
            "Hardcoded ceiling: 100 (ABS_MAX_AGENT_TURNS)."
        ),
    },
    {
        "name": "audit_max_agent_turns",
        "label": "Audit stage — max agent turns",
        "label_suffix": "(advanced)",
        "type": "number",
        "width": "third",
        "min": 1,
        "max": 100,
        "placeholder": "Default: 12",
        "help": "Tighter than analyze by default; audit shouldn't sprawl.",
    },
    {
        "name": "llm_max_tokens",
        "label": "LLM max_tokens per call",
        "label_suffix": "(advanced)",
        "type": "number",
        "width": "third",
        "min": 256,
        "max": 16384,
        "placeholder": "Default: 4096",
        "help": (
            "Applies to every LLM-bearing stage (analyze loop, "
            "synthesize, audit loop, scribe). Hardcoded ceiling: 16384."
        ),
    },
    {
        "name": "step_summary_truncate_chars",
        "label": "Step output_summary truncate (chars)",
        "label_suffix": "(advanced)",
        "type": "number",
        "width": "third",
        "min": 500,
        "max": 50000,
        "placeholder": "Default: 2000",
        "help": (
            "Per-step output_summary text cap. Display/storage concern; "
            "doesn't affect what the LLM sees."
        ),
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT config_schema FROM workflow_types WHERE type_id = 7")
    ).fetchone()
    if not row:
        return
    schema = row[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    if not isinstance(schema, list):
        raise RuntimeError(
            f"type 7 config_schema is not a list: {type(schema).__name__}"
        )
    existing_names = {f.get("name") for f in schema if isinstance(f, dict)}
    for field in NEW_FIELDS:
        if field["name"] in existing_names:
            continue
        schema.append(field)
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(schema)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT config_schema FROM workflow_types WHERE type_id = 7")
    ).fetchone()
    if not row:
        return
    schema = row[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    if not isinstance(schema, list):
        return
    drop_names = {f["name"] for f in NEW_FIELDS}
    new_schema = [
        f for f in schema
        if not (isinstance(f, dict) and f.get("name") in drop_names)
    ]
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(new_schema)},
    )

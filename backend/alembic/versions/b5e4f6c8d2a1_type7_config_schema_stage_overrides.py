"""type 7 config_schema: add stage_overrides repeating_rows (R2)

Revision ID: b5e4f6c8d2a1
Revises: a8b3c5d7e9f2
Create Date: 2026-05-18 00:00:00.000000

R2 of the AgenticEngine configurable-pipeline refactor.

Adds a `stage_overrides` field to the Type 7 (Analyze Data Collection)
workflow type's `config_schema`. The field is a repeating_rows shape
letting users specify per-stage prompt addenda — extra guidance that
gets appended to the prompt for any LLM-bearing stage (analyze,
synthesize, audit, scribe).

The existing dedicated fields (processing_steps → analyze,
report_structure → synthesize, voice_and_style → scribe) continue to
work; this new field is *additional* guidance, not a replacement.

Backwards-compat: workflows without a stage_overrides value behave
identically to before. The Pydantic save-time validators on
UserWorkflowCreate / UserWorkflowUpdate already accept the new key.

Downgrade: removes the stage_overrides field from the schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "b5e4f6c8d2a1"
down_revision: Union[str, None] = "a8b3c5d7e9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STAGE_OVERRIDES_FIELD = {
    "name": "stage_overrides",
    "label": "Per-stage prompt overrides",
    "label_suffix": "(advanced, optional)",
    "type": "repeating_rows",
    "width": "full",
    "min_rows": 0,
    "max_rows": 6,
    "add_label": "Add stage override",
    "help": (
        "Add extra guidance for any LLM-bearing stage. The text is "
        "appended to that stage's existing prompt (it does not replace "
        "the analysis goal, report structure, or voice profile). Stages "
        "that don't appear here use the defaults."
    ),
    "row_schema": [
        {
            "name": "stage",
            "label": "Stage",
            "type": "select",
            "width": "third",
            "options": [
                {"value": "analyze",    "label": "Analyze (data exploration)"},
                {"value": "synthesize", "label": "Synthesize (draft report)"},
                {"value": "audit",      "label": "Audit (critique)"},
                {"value": "scribe",     "label": "Scribe (final polish)"},
            ],
        },
        {
            "name": "addendum",
            "label": "Additional guidance",
            "type": "multiline",
            "width": "full",
            "rows": 3,
            "placeholder": (
                "Extra direction the LLM should follow in this stage. "
                "e.g., 'Emphasize year-over-year deltas over monthly noise.'"
            ),
        },
    ],
}


def upgrade() -> None:
    """Append stage_overrides to the Type 7 config_schema array."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT config_schema FROM workflow_types WHERE type_id = 7")
    ).fetchone()
    if not row:
        # Type 7 missing — nothing to migrate. Earlier migrations would
        # have failed first; surface defensively.
        return
    schema = row[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    if not isinstance(schema, list):
        raise RuntimeError(
            f"type 7 config_schema is not a list: {type(schema).__name__}"
        )
    # Idempotency — if a prior run left the field in place, do nothing.
    if any(isinstance(f, dict) and f.get("name") == "stage_overrides" for f in schema):
        return
    schema.append(STAGE_OVERRIDES_FIELD)
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(schema)},
    )


def downgrade() -> None:
    """Strip stage_overrides from the Type 7 config_schema array."""
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
    new_schema = [
        f for f in schema
        if not (isinstance(f, dict) and f.get("name") == "stage_overrides")
    ]
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(new_schema)},
    )

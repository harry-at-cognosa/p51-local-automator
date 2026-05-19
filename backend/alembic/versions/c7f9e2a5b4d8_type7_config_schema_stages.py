"""type 7 config_schema: add stages checkbox_list (R1 UI)

Revision ID: c7f9e2a5b4d8
Revises: b5e4f6c8d2a1
Create Date: 2026-05-18 00:00:00.000000

Surfaces the `config.stages` override (introduced in R1 of the
configurable-pipeline refactor) in the Type 7 workflow config form.

Renders as a checkbox_list of the six canonical stages, pre-populated
with all six selected so the default matches DEFAULT_STAGES. Unchecking
a stage skips it at run time. The backend validator
(`_validate_stages_override` in `backend/db/schemas.py`) still enforces
the rules: non-empty list, no duplicates, only known stage names.

Inserted *before* `stage_overrides` so the two pipeline-shape knobs sit
together with the upstream choice (which stages run) above the
downstream one (per-stage prompt addenda).

Backwards-compat: workflows without an explicit `stages` value continue
to run the full six-stage default. Idempotent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "c7f9e2a5b4d8"
down_revision: Union[str, None] = "b5e4f6c8d2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_STAGES = ["ingest", "profile", "analyze", "synthesize", "audit", "scribe"]

STAGES_FIELD = {
    "name": "stages",
    "label": "Pipeline stages",
    "label_suffix": "(advanced — uncheck to skip)",
    "type": "checkbox_list",
    "width": "full",
    "options_simple": list(DEFAULT_STAGES),
    "default": list(DEFAULT_STAGES),
    "help": (
        "Choose which stages this workflow runs. The default is all six. "
        "Common skip patterns: uncheck audit + scribe for a draft-only run "
        "(faster, cheaper); uncheck analyze + audit for a descriptive-only "
        "report. Stage data dependencies still apply at run time — "
        "synthesize expects analyze findings, audit expects a synthesized "
        "draft, scribe expects an audit critique."
    ),
}


def upgrade() -> None:
    """Insert `stages` into the Type 7 config_schema array, just before
    `stage_overrides` if present, otherwise appended."""
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
    # Idempotency — bail if already inserted.
    if any(isinstance(f, dict) and f.get("name") == "stages" for f in schema):
        return
    # Find stage_overrides position to insert just before it.
    insert_at = len(schema)
    for i, f in enumerate(schema):
        if isinstance(f, dict) and f.get("name") == "stage_overrides":
            insert_at = i
            break
    schema.insert(insert_at, STAGES_FIELD)
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(schema)},
    )


def downgrade() -> None:
    """Strip the `stages` field from the Type 7 config_schema array."""
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
        if not (isinstance(f, dict) and f.get("name") == "stages")
    ]
    bind.execute(
        sa.text("UPDATE workflow_types SET config_schema = :s WHERE type_id = 7"),
        {"s": json.dumps(new_schema)},
    )

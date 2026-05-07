"""seed Agentic category + Analyze Data Collection workflow type (A1.2)

Revision ID: d3b6f9a2c4e7
Revises: c2a4d7e8b3f9
Create Date: 2026-05-07 00:10:00.000000

Inserts the `agentic` workflow_categories row and the new "Analyze Data
Collection" workflow_types row (AWF-1). The type ships with:

- schedulable=FALSE (cron-trigger disallowed; UI hides schedule controls)
- enabled=TRUE (visible in the workflow catalog so users can author specs)
- six-field config_schema covering data definition, analysis goal,
  processing steps, report structure, voice and style, report filename slug

The schema is rendered by SchemaConfigForm — no hand-tuned branch in
WorkflowConfigForm.tsx is added. Frontend gates the Run Now button on
type_name (A1.4) until A3 lands the engine.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = 'd3b6f9a2c4e7'
down_revision: Union[str, None] = 'c2a4d7e8b3f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROCESSING_STEPS_DEFAULT = (
    "1. Ingest the data for processing by the available agents and skills. "
    "Review the descriptions of each table and the attribute and entity names.\n\n"
    "2. Review the data tables provided, including the descriptive information, "
    "and characterize the populations of data entities and attributes — focusing on "
    "which data are likely to inform the analysis goal.\n\n"
    "3. Once each table has been examined, use the semantics implied by column "
    "names and the provided descriptions to identify potentially relevant "
    "relationships within and between attributes. Perform inter-table analyses "
    "to gather evidence relevant to the workflow goal.\n\n"
    "4. Formulate a comprehensive but concise report addressing the goal. This "
    "minimum set may be expanded by the agent — each step may specify one or "
    "more artifacts (a chart, a table, a paragraph of observations or conclusions)."
)


CONFIG_SCHEMA = [
    {
        "name": "data_definition",
        "label": "Data Tables",
        "type": "repeating_rows",
        "width": "full",
        "min_rows": 1,
        "max_rows": 10,
        "add_label": "Add table",
        "help": "Each table is a CSV or XLSX file plus a one- or two-sentence description of what it is and what it's for.",
        "row_schema": [
            {
                "name": "file",
                "label": "Table File",
                "type": "file_picker",
                "width": "half",
                "filter_extensions": ["csv", "xlsx"],
            },
            {
                "name": "description",
                "label": "Description",
                "type": "multiline",
                "width": "half",
                "rows": 2,
                "placeholder": "What this data is, broadly, and what it means or is to be used for.",
            },
        ],
    },
    {
        "name": "analysis_goal",
        "label": "Analysis Goal",
        "type": "multiline",
        "width": "full",
        "rows": 4,
        "placeholder": "A question to address, a claim to verify or disprove, or a trend / correlation / relationship to investigate.",
        "help": "Markdown allowed.",
    },
    {
        "name": "processing_steps",
        "label": "Processing Steps",
        "type": "multiline",
        "width": "full",
        "rows": 10,
        "default": PROCESSING_STEPS_DEFAULT,
        "help": "Markdown allowed. The agent may add steps it considers necessary.",
    },
    {
        "name": "report_structure",
        "label": "Report Structure",
        "type": "multiline",
        "width": "full",
        "rows": 6,
        "placeholder": "What sections the final report should include and in what order. High-level guidance is fine.",
        "help": "Markdown allowed. Consumed by the synthesize stage.",
    },
    {
        "name": "voice_and_style",
        "label": "Voice and Style",
        "type": "multiline",
        "width": "full",
        "rows": 4,
        "placeholder": "Tone, brevity, jargon avoidance, branding. Paste a voice profile from your library if you have one.",
        "help": "Markdown allowed. Consumed by the scribe stage.",
    },
    {
        "name": "report_filename",
        "label": "Report Filename Slug",
        "label_suffix": "(optional)",
        "type": "string",
        "width": "half",
        "placeholder": "e.g. q1_revenue_signals",
        "help": "Used as the basename of the final markdown report. If blank, a default is generated. Max 60 characters.",
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Insert Agentic category. Sort 50 — sits after the existing
    #    email/calendar/analysis/queries categories (10/20/30/40).
    bind.execute(
        sa.text(
            "INSERT INTO workflow_categories (category_key, short_name, long_name, sort_order, enabled) "
            "VALUES (:k, :s, :l, :o, TRUE) "
            "ON CONFLICT (category_key) DO NOTHING"
        ),
        {"k": "agentic", "s": "Agentic", "l": "Agentic AI Workflows", "o": 50},
    )

    # 2. Insert the AWF-1 type. ON CONFLICT keeps re-runs idempotent during dev.
    bind.execute(
        sa.text(
            "INSERT INTO workflow_types ("
            "  type_name, type_desc, category_id, short_name, long_name, "
            "  default_config, required_services, config_schema, enabled, schedulable"
            ") VALUES ("
            "  :tn, :td, "
            "  (SELECT category_id FROM workflow_categories WHERE category_key = 'agentic'), "
            "  :sn, :ln, "
            "  CAST(:dc AS json), CAST(:rs AS json), CAST(:cs AS json), TRUE, FALSE"
            ") ON CONFLICT (type_name) DO NOTHING"
        ),
        {
            "tn": "Analyze Data Collection",
            "td": (
                "Multi-stage agentic analysis of one or more data tables. The user "
                "supplies tables with descriptions, an analysis goal, processing "
                "steps, report structure, and voice/style guidance. The engine "
                "runs ingest, profile, analyze, synthesize, audit, and scribe "
                "stages, producing a markdown report plus supporting artifacts. "
                "Manual-trigger only; not schedulable."
            ),
            "sn": "Data Analyst",
            "ln": "Analyze Data Collection",
            "dc": json.dumps({}),
            "rs": json.dumps([]),
            "cs": json.dumps(CONFIG_SCHEMA),
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Remove the type first (FK to category), then the category.
    bind.execute(
        sa.text("DELETE FROM workflow_types WHERE type_name = 'Analyze Data Collection'")
    )
    bind.execute(
        sa.text("DELETE FROM workflow_categories WHERE category_key = 'agentic'")
    )

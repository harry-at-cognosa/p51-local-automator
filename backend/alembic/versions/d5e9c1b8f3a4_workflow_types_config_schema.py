"""workflow_types.config_schema column + populate for 6 types

Revision ID: d5e9c1b8f3a4
Revises: c4f1a8e9b2d6
Create Date: 2026-05-05 00:30:00.000000

Adds a `config_schema` JSON column on workflow_types describing the
fields a user_workflow's config carries. Frontend's generic schema-driven
renderer reads this and renders an appropriate input per field.

The existing per-typeId form branches in WorkflowConfigForm.tsx remain
the primary editor for types 1–6; the populated schemas here are
worked examples that the generic renderer also supports, plus a
reference for authors of future workflow types.

Schema format (a list of field descriptors):

    [
      {
        "name": "field_key",
        "label": "Display Label",
        "label_suffix": "(optional muted text after label)",
        "type": "string" | "multiline" | "number" | "date" |
                "string_list" | "select" | "checkbox_list",
        "default": <default value>,
        "placeholder": "...",
        "help": "muted help text under the field",
        "width": "third" | "half" | "full",       # bootstrap col size
        "options": [{"value": "v", "label": "L"}], # for select
        "options_simple": ["A", "B"],              # for checkbox_list
        "min": 1, "max": 200,                      # for number
        "rows": 4, "mono": true,                   # for multiline
        "show_badges": true                        # for string_list
      },
      ...
    ]
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = 'd5e9c1b8f3a4'
down_revision: Union[str, None] = 'c4f1a8e9b2d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MAIL_ACCOUNT_OPTIONS = [
    {"value": "iCloud", "label": "iCloud (harry.layman@icloud.com)"},
    {"value": "harry@cognosa.net", "label": "Cognosa (harry@cognosa.net)"},
    {"value": "Exchange", "label": "Exchange / CogWrite (legacy)"},
]

_PERIOD_OPTIONS = [
    {"value": p, "label": p} for p in [
        "last 24 hours", "last 3 days", "last 7 days", "last 2 weeks", "last month",
    ]
]


SCHEMAS: dict[int, list[dict]] = {
    1: [
        {"name": "account", "label": "Mail Account", "type": "select",
         "options": _MAIL_ACCOUNT_OPTIONS, "default": "iCloud", "width": "half"},
        {"name": "mailbox", "label": "Mailbox", "type": "string",
         "default": "INBOX", "width": "half"},
        {"name": "period", "label": "Time Period", "type": "select",
         "options": _PERIOD_OPTIONS, "default": "last 7 days", "width": "half"},
        {"name": "topics", "label": "Topics",
         "label_suffix": "(leave empty for AI to decide)",
         "type": "string_list",
         "placeholder": "Business & Finance, Technology & AI, ...",
         "show_badges": True, "width": "half"},
        {"name": "scope", "label": "Scope",
         "label_suffix": '("all" = everything, or describe a focus area)',
         "type": "string",
         "placeholder": 'e.g. "all", "AI and machine learning", "client projects"',
         "help": "When set, the AI will only categorize emails related to this scope and skip the rest.",
         "width": "full"},
    ],
    2: [
        {"name": "file_path", "label": "Data File Path", "type": "string",
         "placeholder": "/path/to/data.csv or .xlsx",
         "help": "Full path to CSV or Excel file on the server",
         "width": "full"},
        {"name": "start_date", "label": "Start Date", "type": "date", "width": "third"},
        {"name": "end_date", "label": "End Date", "type": "date", "width": "third"},
        {"name": "output_format", "label": "Output Format", "type": "select",
         "options": [{"value": "xlsx", "label": "Excel (.xlsx)"}, {"value": "csv", "label": "CSV"}],
         "default": "xlsx", "width": "third"},
        {"name": "key_fields", "label": "Key Fields",
         "label_suffix": "(optional, AI decides if blank)",
         "type": "string_list",
         "placeholder": "date, amount, category, vendor",
         "width": "full"},
    ],
    3: [
        {"name": "calendars", "label": "Calendars", "type": "checkbox_list",
         "options_simple": ["Work", "Family", "Home", "Calendar"],
         "default": ["Work", "Family"], "width": "half"},
        {"name": "days", "label": "Days Ahead", "type": "number",
         "min": 1, "max": 90, "default": 7, "width": "half"},
    ],
    4: [
        {"name": "query_name", "label": "Query Name", "type": "string",
         "placeholder": "e.g. daily_sales_summary", "width": "half"},
        {"name": "connection_string", "label": "Connection String", "type": "string",
         "placeholder": "postgresql://user:pass@localhost:5432/dbname", "width": "half"},
        {"name": "query", "label": "SQL Query", "type": "multiline",
         "rows": 4, "mono": True, "placeholder": "SELECT ...",
         "help": "Read-only queries only (SELECT, WITH, EXPLAIN)",
         "width": "full"},
    ],
    5: [
        {"name": "account", "label": "Mail Account", "type": "select",
         "options": _MAIL_ACCOUNT_OPTIONS, "default": "iCloud",
         "help": "Drafts/sends use this account", "width": "half"},
        {"name": "mailbox", "label": "Mailbox", "type": "string",
         "default": "INBOX", "width": "half"},
        {"name": "sender_filter", "label": "Sender filter (substring, case-insensitive)",
         "type": "string",
         "placeholder": "e.g. form-submission@squarespace.info", "width": "half"},
        {"name": "fetch_limit", "label": "Fetch limit", "type": "number",
         "min": 1, "max": 200, "default": 50,
         "help": "Max recent messages to scan per run", "width": "half"},
        {"name": "body_contains", "label": "Body contains (substring, case-insensitive)",
         "type": "string",
         "placeholder": "e.g. Sent via form submission",
         "help": "At least one filter (sender or body) is required — empty-filter runs are skipped to avoid unintended replies.",
         "width": "full"},
        {"name": "body_email_field", "label": "Submitter-email body label (optional)",
         "type": "string",
         "placeholder": "e.g. Email:",
         "help": "For form-submission emails where the From is a no-reply transport, specify the body label that precedes the actual submitter's email. Leave blank for emails with a real Reply-To header.",
         "width": "full"},
        {"name": "tone", "label": "Reply tone", "type": "string",
         "placeholder": "e.g. warm and professional",
         "default": "warm and professional", "width": "full"},
        {"name": "signature", "label": "Signature (appended to every reply)",
         "type": "multiline", "rows": 3, "mono": True,
         "placeholder": "Harry Layman\nCognosa",
         "width": "full"},
    ],
}
# Type 6 has the same shape as type 5 (shared engine).
SCHEMAS[6] = SCHEMAS[5]


def upgrade() -> None:
    op.add_column(
        "workflow_types",
        sa.Column("config_schema", sa.JSON(), nullable=True),
    )
    for type_id, schema in SCHEMAS.items():
        op.execute(
            sa.text(
                "UPDATE workflow_types SET config_schema = CAST(:s AS json) WHERE type_id = :t"
            ).bindparams(s=json.dumps(schema), t=type_id)
        )


def downgrade() -> None:
    op.drop_column("workflow_types", "config_schema")

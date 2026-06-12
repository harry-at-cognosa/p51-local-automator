"""seed Calendar Digest with Context workflow type (type 9)

Revision ID: a8b3c5d7e2f6
Revises: f9c2a7e1b8d4
Create Date: 2026-06-11 00:00:00.000000

Inserts the "Calendar Digest with Context" workflow_types row in the calendar
category:

- type_id pinned to 9 (the runner dispatch keys on type_id == 9); the
  workflow_types sequence is reset afterward so subsequent inserts continue
  cleanly.
- schedulable=TRUE   (intended to fire daily like Type 3)
- emailable_results=TRUE (the digest is the typical deliverable)
- enabled=TRUE
- config_schema=NULL — uses a hand-tuned form (Type9CalendarContextForm in
  WorkflowConfigForm.tsx) because the service/calendar picker has dynamic
  dropdowns the schema-driven form doesn't model.

This is Type 3's spiritual successor — Type 3 keeps running for existing
workflows. New behavior in Type 9:
  - Importance + tentative read from event title markers (*Title* / |Title|)
  - Reminder-pattern events excluded from conflict math and shown as dots
  - Cross-calendar synonym groups collapse duplicates
  - Conflicts are visual (PNG time grid), not LLM-asserted
  - LLM writes only a single summary paragraph, primed by context_text
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "a8b3c5d7e2f6"
down_revision: Union[str, None] = "f9c2a7e1b8d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TYPE_DESC = (
    "Calendar digest with user-supplied context: free-form description of the "
    "digest's job, reminder-event patterns excluded from conflict detection, "
    "and cross-calendar synonym groups that collapse duplicates. Importance "
    "and tentative status read directly from event-title markers "
    "(*Important*, |maybe|) instead of LLM guesswork. Includes a visual time "
    "grid PNG for the next up-to-7 days so adjacency and overlap are obvious "
    "to the reader."
)

DEFAULT_CONFIG = {
    "service": "apple_calendar",
    "calendars": ["Work", "Family"],
    "days": 7,
    "context_text": "",
    "reminder_patterns": [],
    "synonym_groups": [],
}


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "INSERT INTO workflow_types ("
            "  type_id, type_name, type_desc, category_id, short_name, long_name, "
            "  default_config, required_services, config_schema, enabled, "
            "  schedulable, emailable_results"
            ") VALUES ("
            "  9, :tn, :td, "
            "  (SELECT category_id FROM workflow_categories WHERE category_key = 'calendar'), "
            "  :sn, :ln, "
            "  CAST(:dc AS json), CAST(:rs AS json), NULL, TRUE, TRUE, TRUE"
            ") ON CONFLICT (type_name) DO NOTHING"
        ),
        {
            "tn": "Calendar Digest with Context",
            "td": TYPE_DESC,
            "sn": "Context Digest",
            "ln": "Calendar Digest with Context",
            "dc": json.dumps(DEFAULT_CONFIG),
            "rs": json.dumps([]),
        },
    )

    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('workflow_types', 'type_id'), "
            "(SELECT MAX(type_id) FROM workflow_types))"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM workflow_types WHERE type_name = 'Calendar Digest with Context'")
    )

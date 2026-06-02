"""seed Email Reaper workflow type (type 8) + reaper settings defaults

Revision ID: f9c2a7e1b8d4
Revises: c9e3f1d7a8b2
Create Date: 2026-06-01 00:00:00.000000

Inserts the "Email Reaper" workflow_types row in the email category:

- type_id pinned to 8 (the runner dispatch keys on type_id == 8); the
  workflow_types sequence is reset afterward so subsequent inserts continue
  cleanly.
- schedulable=TRUE   (manual + cron both move old mail to Trash)
- emailable_results=TRUE (the deletion report can be emailed to the owner)
- enabled=TRUE
- config_schema=NULL — Email Reaper uses a hand-tuned form
  (Type8EmailReaperForm in WorkflowConfigForm.tsx), not the schema-driven
  SchemaConfigForm.

Also seeds the two reaper numeric limits into api_settings (mirrors the
SETTING_REAPER_* constants in workflow_engine.py):
  reaper_max_senders               150  — max sender rows per workflow
  reaper_fetch_limit_per_sender    500  — max messages scanned per sender/run
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "f9c2a7e1b8d4"
down_revision: Union[str, None] = "c9e3f1d7a8b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TYPE_DESC = (
    "Move to Trash all emails from a configurable list of sender addresses "
    "that are older than each sender's safety window (5-365 days). Operates on "
    "one account (Apple Mail, Workspace Gmail, or consumer Gmail). Runs in "
    "preview mode by default (reports matches without deleting); turn preview "
    "off to actually move matches to Trash. Always writes a deletion report."
)

DEFAULT_CONFIG = {
    "service": "apple_mail",
    "account": "iCloud",
    "senders": [],
    "preview_only": True,
}

SETTINGS_DEFAULTS: list[tuple[str, str]] = [
    ("reaper_max_senders",            "150"),
    ("reaper_fetch_limit_per_sender", "500"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # Insert the Email Reaper type with an explicit type_id so the runner's
    # WORKFLOW_RUNNERS[8] dispatch is stable. ON CONFLICT keeps re-runs
    # idempotent during dev.
    bind.execute(
        sa.text(
            "INSERT INTO workflow_types ("
            "  type_id, type_name, type_desc, category_id, short_name, long_name, "
            "  default_config, required_services, config_schema, enabled, "
            "  schedulable, emailable_results"
            ") VALUES ("
            "  8, :tn, :td, "
            "  (SELECT category_id FROM workflow_categories WHERE category_key = 'email'), "
            "  :sn, :ln, "
            "  CAST(:dc AS json), CAST(:rs AS json), NULL, TRUE, TRUE, TRUE"
            ") ON CONFLICT (type_name) DO NOTHING"
        ),
        {
            "tn": "Email Reaper",
            "td": TYPE_DESC,
            "sn": "Email Reaper",
            "ln": "Email Reaper",
            "dc": json.dumps(DEFAULT_CONFIG),
            "rs": json.dumps([]),
        },
    )

    # Keep the serial sequence ahead of the highest explicit id.
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('workflow_types', 'type_id'), "
            "(SELECT MAX(type_id) FROM workflow_types))"
        )
    )

    for name, value in SETTINGS_DEFAULTS:
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
    bind.execute(sa.text("DELETE FROM workflow_types WHERE type_name = 'Email Reaper'"))
    names = [n for n, _ in SETTINGS_DEFAULTS]
    bind.execute(
        sa.text("DELETE FROM api_settings WHERE name = ANY(:names)"),
        {"names": names},
    )

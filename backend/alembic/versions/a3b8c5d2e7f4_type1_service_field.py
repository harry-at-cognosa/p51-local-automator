"""type 1 config_schema: add `service` field for Gmail support (B1.9)

Revision ID: a3b8c5d2e7f4
Revises: d1c8f4e2b9a3
Create Date: 2026-05-06 00:00:00.000000

Type 1 (Email Topic Monitor) gains a `service` field that selects
between apple_mail (existing) and gmail (Track B Phase B1).

The hand-tuned typeId===1 branch in WorkflowConfigForm.tsx is the
primary editor — that's where the conditional gmail-account picker
lives. This migration updates the workflow_types.config_schema
metadata so the F3 snapshot panel (and any future schema-driven
renderer) renders the correct field labels.

default_config already includes "service": "apple_mail" via seed.py;
no default_config edit needed in this migration.

Existing user_workflows rows whose config.service is unset continue
to work — the engine reads `config.get("service", "apple_mail")`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = 'a3b8c5d2e7f4'
down_revision: Union[str, None] = 'd1c8f4e2b9a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SERVICE_OPTIONS = [
    {"value": "apple_mail", "label": "Apple Mail"},
    {"value": "gmail",      "label": "Gmail (Workspace)"},
]

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


_TYPE1_NEW_SCHEMA = [
    {"name": "service", "label": "Email Service", "type": "select",
     "options": _SERVICE_OPTIONS, "default": "apple_mail", "width": "half"},
    {"name": "account", "label": "Mail Account",
     "label_suffix": "(Apple Mail)", "type": "select",
     "options": _MAIL_ACCOUNT_OPTIONS, "default": "iCloud", "width": "half",
     "help": "Used when service = Apple Mail."},
    {"name": "account_id", "label": "Gmail Account",
     "label_suffix": "(Gmail)", "type": "number",
     "help": "GmailAccounts.id of a connected account; populated by the form when service = Gmail.",
     "width": "half"},
    {"name": "mailbox", "label": "Mailbox / Label", "type": "string",
     "default": "INBOX", "width": "half",
     "help": "Apple Mail mailbox name, or Gmail label id (INBOX, SPAM, custom labels)."},
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
]


# Restore-on-downgrade snapshot of the prior schema (from migration
# d5e9c1b8f3a4) so reverting this migration doesn't leave the column null.
_TYPE1_PRIOR_SCHEMA = [
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
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workflow_types SET config_schema = CAST(:s AS json) WHERE type_id = 1"
        ).bindparams(s=json.dumps(_TYPE1_NEW_SCHEMA))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workflow_types SET config_schema = CAST(:s AS json) WHERE type_id = 1"
        ).bindparams(s=json.dumps(_TYPE1_PRIOR_SCHEMA))
    )

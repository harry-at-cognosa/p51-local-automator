"""email-results: outbound prefs + workflow_types.emailable_results + run-email log

Revision ID: b6d4e2c9f8a7
Revises: f4c8d2e9a3b6
Create Date: 2026-05-25 00:00:00.000000

Adds the schema backbone for the "email me the results" final-step feature:

- api_users.outbound_service / outbound_identifier: the user's designated
  outbound email account (one of apple_mail | gmail | gmail_imap). For gmail
  the identifier is the gmail_accounts.id; for gmail_imap it's the email
  address; for apple_mail it's the Mail.app account name plus a separate
  destination email (stored in a tiny JSON blob on outbound_identifier when
  service=apple_mail; chosen over a third column to keep the User table flat).
- workflow_types.emailable_results: per-type opt-in flag, default FALSE.
  Seeds TRUE for type_id 1 (Email Topic Monitor) and 3 (Calendar Digest).
- workflow_run_email_log: per-run delivery log. The run's `status` is NOT
  changed by email outcome; this table is the source of truth for whether
  delivery succeeded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = 'b6d4e2c9f8a7'
down_revision: Union[str, None] = 'f4c8d2e9a3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_users",
        sa.Column("outbound_service", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "api_users",
        sa.Column("outbound_identifier", sa.String(length=512), nullable=True),
    )

    op.add_column(
        "workflow_types",
        sa.Column(
            "emailable_results",
            sa.Boolean(),
            server_default=sa.text("'FALSE'"),
            nullable=False,
        ),
    )
    op.execute(
        text(
            "UPDATE workflow_types SET emailable_results = TRUE "
            "WHERE type_id IN (1, 3)"
        )
    )

    op.create_table(
        "workflow_run_email_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(
                "workflow_runs.run_id",
                name="fk_workflow_run_email_log_run_id",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_run_email_log")
    op.drop_column("workflow_types", "emailable_results")
    op.drop_column("api_users", "outbound_identifier")
    op.drop_column("api_users", "outbound_service")

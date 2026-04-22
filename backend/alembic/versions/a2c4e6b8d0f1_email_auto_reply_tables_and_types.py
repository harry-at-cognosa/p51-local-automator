"""Email auto-reply: pending queue + dedup log + 2 new workflow types

Revision ID: a2c4e6b8d0f1
Revises: f1a2b3c4d5e6
Create Date: 2026-04-22 13:00:00.000000

Adds two new workflow types in the email category:
  - Auto-Reply (Draft Only): generate reply and save to Drafts via AppleScript
  - Auto-Reply (Approve Before Send): queue reply for human approval in-app

Adds:
  - pending_email_replies: Variant B queue (per-message pending state)
  - email_auto_reply_log: dedup ledger so scheduled runs don't re-ack
  - Seeds the two new type rows (seed.py also upserts them so idempotent)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2c4e6b8d0f1'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_TYPES = [
    {
        "type_name": "Auto-Reply (Draft Only)",
        "type_desc": "Scan inbox for matching emails, generate an acknowledgment reply with AI, and save it to the account's Drafts folder. No email is sent automatically.",
        "category_key": "email",
        "short_name": "Draft Reply",
        "long_name": "Auto-Reply (Draft Only)",
    },
    {
        "type_name": "Auto-Reply (Approve Before Send)",
        "type_desc": "Scan inbox for matching emails, generate an acknowledgment reply with AI, and queue it in the app for human approval. User can approve, edit and send, save as draft, or reject each reply.",
        "category_key": "email",
        "short_name": "Approve Reply",
        "long_name": "Auto-Reply (Approve Before Send)",
    },
]


def upgrade() -> None:
    # pending_email_replies — Variant B queue
    op.create_table(
        "pending_email_replies",
        sa.Column("pending_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("source_account", sa.VARCHAR(length=128), nullable=False),
        sa.Column("source_mailbox", sa.VARCHAR(length=128), nullable=False),
        sa.Column("source_from", sa.VARCHAR(), nullable=False),
        sa.Column("source_subject", sa.VARCHAR(), nullable=False),
        sa.Column("to_address", sa.VARCHAR(), nullable=False),
        sa.Column("subject", sa.VARCHAR(), nullable=False),
        sa.Column("body_draft", sa.Text(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("user_action", sa.VARCHAR(length=32), nullable=True),
        sa.Column("final_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["user_workflows.workflow_id"], name="fk_pending_replies_workflow_id"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name="fk_pending_replies_run_id"),
        sa.PrimaryKeyConstraint("pending_id"),
    )
    op.create_index(
        "ix_pending_replies_workflow_status",
        "pending_email_replies",
        ["workflow_id", "status"],
        unique=False,
    )

    # email_auto_reply_log — dedup ledger (one row per acknowledged message)
    op.create_table(
        "email_auto_reply_log",
        sa.Column("log_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("source_account", sa.VARCHAR(length=128), nullable=False),
        sa.Column("action", sa.VARCHAR(length=32), nullable=False),
        sa.Column("pending_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["user_workflows.workflow_id"], name="fk_auto_reply_log_workflow_id"),
        sa.ForeignKeyConstraint(["pending_id"], ["pending_email_replies.pending_id"], name="fk_auto_reply_log_pending_id"),
        sa.PrimaryKeyConstraint("log_id"),
        sa.UniqueConstraint("workflow_id", "source_message_id", name="uq_auto_reply_log_workflow_msg"),
    )

    # Seed the two new workflow types in the email category
    bind = op.get_bind()
    for t in NEW_TYPES:
        bind.execute(
            sa.text(
                "INSERT INTO workflow_types "
                "(type_name, type_desc, category_id, short_name, long_name, default_config, required_services, enabled) "
                "VALUES (:n, :d, "
                "(SELECT category_id FROM workflow_categories WHERE category_key = :ck), "
                ":sn, :ln, :dc, :rs, TRUE) "
                "ON CONFLICT (type_name) DO NOTHING"
            ),
            {
                "n": t["type_name"],
                "d": t["type_desc"],
                "ck": t["category_key"],
                "sn": t["short_name"],
                "ln": t["long_name"],
                "dc": '{"account":"iCloud","mailbox":"INBOX","period":"last 7 days","sender_filter":"","body_contains":"","signature":""}',
                "rs": '["apple_mail_mcp"]',
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for t in NEW_TYPES:
        bind.execute(
            sa.text("DELETE FROM workflow_types WHERE type_name = :n"),
            {"n": t["type_name"]},
        )

    op.drop_table("email_auto_reply_log")
    op.drop_index("ix_pending_replies_workflow_status", table_name="pending_email_replies")
    op.drop_table("pending_email_replies")

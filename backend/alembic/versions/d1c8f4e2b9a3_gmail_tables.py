"""gmail_accounts + gmail_token_usage tables (B1.2)

Revision ID: d1c8f4e2b9a3
Revises: f7a9b3d8c1e0
Create Date: 2026-05-06 00:00:00.000000

Two tables for Track B Phase B1 (read-only Gmail integration):

- gmail_accounts: per-user OAuth-connected Gmail accounts with encrypted
  refresh + access tokens. UNIQUE(user_id, email) — a user connects a
  given Gmail address once.
- gmail_token_usage: audit log of every gmail_client.py call, including
  OAuth lifecycle events (connect, refresh, revoke). Indexed for "recent
  activity" queries.

Encrypted token columns are BYTEA. The encryption helper at
backend/services/secrets.py handles the AES-GCM round-trip; the DB
sees only opaque blobs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1c8f4e2b9a3'
down_revision: Union[str, None] = 'f7a9b3d8c1e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("api_users.user_id", name="fk_gmail_accounts_user_id"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("api_groups.group_id", name="fk_gmail_accounts_group_id"),
            nullable=False,
        ),
        sa.Column("email", sa.VARCHAR(255), nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "email", name="uq_gmail_accounts_user_email"),
    )

    op.create_table(
        "gmail_token_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("gmail_accounts.id", name="fk_gmail_token_usage_account_id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.VARCHAR(50), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("error_detail", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_gmail_token_usage_account_timestamp",
        "gmail_token_usage",
        ["account_id", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_token_usage_account_timestamp", table_name="gmail_token_usage")
    op.drop_table("gmail_token_usage")
    op.drop_table("gmail_accounts")

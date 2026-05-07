"""encrypt existing type-4 connection_string values (T4.3)

Revision ID: b8e5d3f1a4c7
Revises: a3b8c5d2e7f4
Create Date: 2026-05-06 00:00:00.000000

Walks user_workflows where type_id=4 and converts any plaintext
config.connection_string into config.connection_string_enc
(base64-encoded AES-GCM ciphertext) via backend.services.secrets.

Uses TOKEN_ENCRYPTION_KEY from the environment. If unset, the
migration fails with a clear message — the customer must configure
encryption before this can run.

Idempotent: rows that already have connection_string_enc (e.g.
created via the T4.2 API path) are skipped. Rows with empty/missing
plaintext are also skipped.

Downgrade is a no-op. Encryption is one-way; reverting to plaintext
would defeat the purpose. Customers who need to roll back must
recreate workflows from a backup taken before this migration ran.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e5d3f1a4c7'
down_revision: Union[str, None] = 'a3b8c5d2e7f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lazy import: alembic discovers all migrations at startup, and we don't
    # want to crash the migration loader if TOKEN_ENCRYPTION_KEY happens to
    # be unset for an unrelated migration run. The encrypt path only fires
    # if there's actually something to encrypt.
    from backend.services import secrets

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT workflow_id, config FROM user_workflows "
            "WHERE type_id = 4"
        )
    ).fetchall()

    encrypted_count = 0
    for workflow_id, config in rows:
        if not isinstance(config, dict):
            continue
        if config.get("connection_string_enc"):
            continue
        plaintext = config.get("connection_string")
        if not plaintext:
            continue
        new_config = dict(config)
        new_config["connection_string_enc"] = secrets.encrypt_to_b64(plaintext)
        new_config.pop("connection_string", None)
        bind.execute(
            sa.text(
                "UPDATE user_workflows SET config = CAST(:c AS json) "
                "WHERE workflow_id = :w"
            ).bindparams(c=__import__("json").dumps(new_config), w=workflow_id)
        )
        encrypted_count += 1

    print(f"[T4.3] Encrypted plaintext connection_string for {encrypted_count} type-4 workflow(s).")


def downgrade() -> None:
    # Intentional no-op. See module docstring.
    pass

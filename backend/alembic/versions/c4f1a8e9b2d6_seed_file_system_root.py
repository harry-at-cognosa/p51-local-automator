"""seed api_settings.file_system_root global default

Revision ID: c4f1a8e9b2d6
Revises: b3e7d2f4a1c8
Create Date: 2026-05-05 00:10:00.000000

Inserts a global api_settings row for `file_system_root` so that every
workflow run has a path to fall back to even if no per-group override is
set. Per-group overrides live in group_settings as the higher-precedence
value; the absence of a per-group row means "use the global default."

Default value here is the desktop-deployment path. On the Mac Mini server
deployment, the operator overrides via the Global Settings UI (or directly
via SQL) before running workflows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a8e9b2d6'
down_revision: Union[str, None] = 'b3e7d2f4a1c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_VALUE = "/Users/harry/p51_output_area"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO api_settings (name, value) "
            "VALUES ('file_system_root', :v) "
            "ON CONFLICT (name) DO NOTHING"
        ).bindparams(v=DEFAULT_VALUE)
    )


def downgrade() -> None:
    # Remove only the api_settings row. Leave any per-group overrides in
    # place — operators may have set them deliberately.
    op.execute("DELETE FROM api_settings WHERE name = 'file_system_root'")

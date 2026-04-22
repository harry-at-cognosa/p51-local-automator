"""Workflow categories + soft-delete on user_workflows + list redesign support

Revision ID: f1a2b3c4d5e6
Revises: 4dcda9cfbcae
Create Date: 2026-04-21 22:00:00.000000

Adds a workflow_categories table and reworks workflow_types to reference it
by FK (category_id), plus short_name and long_name for display. Drops the
ad-hoc type_category string. Adds a soft-delete `deleted` column to
user_workflows. Adds perf indexes for list queries.

Backfill mapping for the 4 seeded types:
    - Email Topic Monitor       -> category 'email'
    - Calendar Digest           -> category 'calendar'
    - Transaction Data Analyzer -> category 'analysis'  (was 'data')
    - SQL Query Runner          -> category 'queries'   (was 'data')

Downgrade is lossy for any non-seeded types that had type_category values
outside the mapped set — that data is restored to a sensible default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '4dcda9cfbcae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed data carried in the migration so the table is usable immediately
# after upgrade. Seed.py will upsert on next startup, keeping these in sync.
CATEGORY_SEED = [
    ("email", "Email", "Email", 10),
    ("calendar", "Calendar", "Calendar", 20),
    ("analysis", "Analysis", "Data Set Analysis", 30),
    ("queries", "Queries", "Structured Queries", 40),
]

# (type_name, category_key, short_name, long_name)
TYPE_BACKFILL = [
    ("Email Topic Monitor", "email", "Topic Monitor", "Email Topic Monitor"),
    ("Calendar Digest", "calendar", "Digest", "Calendar Digest"),
    ("Transaction Data Analyzer", "analysis", "Transactions", "Transaction Data Analyzer"),
    ("SQL Query Runner", "queries", "SQL Runner", "SQL Query Runner"),
]


def upgrade() -> None:
    # 1. workflow_categories table
    op.create_table(
        "workflow_categories",
        sa.Column("category_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_key", sa.VARCHAR(length=32), nullable=False),
        sa.Column("short_name", sa.VARCHAR(length=32), nullable=False),
        sa.Column("long_name", sa.VARCHAR(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("'TRUE'"), nullable=False),
        sa.PrimaryKeyConstraint("category_id"),
        sa.UniqueConstraint("category_key", name="uq_workflow_categories_key"),
    )

    # 2. add nullable columns to workflow_types (filled in during data migration)
    op.add_column("workflow_types", sa.Column("category_id", sa.Integer(), nullable=True))
    op.add_column("workflow_types", sa.Column("short_name", sa.VARCHAR(length=32), nullable=True))
    op.add_column("workflow_types", sa.Column("long_name", sa.VARCHAR(length=128), nullable=True))

    # 3. data migration
    bind = op.get_bind()
    for key, short, long_, order in CATEGORY_SEED:
        bind.execute(
            sa.text(
                "INSERT INTO workflow_categories (category_key, short_name, long_name, sort_order) "
                "VALUES (:k, :s, :l, :o)"
            ),
            {"k": key, "s": short, "l": long_, "o": order},
        )

    for type_name, category_key, short, long_ in TYPE_BACKFILL:
        bind.execute(
            sa.text(
                "UPDATE workflow_types SET "
                "category_id = (SELECT category_id FROM workflow_categories WHERE category_key = :ck), "
                "short_name = :s, "
                "long_name = :l "
                "WHERE type_name = :tn"
            ),
            {"ck": category_key, "s": short, "l": long_, "tn": type_name},
        )

    # Any types NOT in the canonical seed fall back to 'analysis' to keep NOT NULL
    # constraint happy. Logs a warning via raise if you want strict — here we're
    # lenient since the project has only the 4 seeded types in practice.
    bind.execute(
        sa.text(
            "UPDATE workflow_types SET "
            "category_id = (SELECT category_id FROM workflow_categories WHERE category_key = 'analysis'), "
            "short_name = COALESCE(short_name, LEFT(type_name, 32)), "
            "long_name = COALESCE(long_name, type_name) "
            "WHERE category_id IS NULL"
        )
    )

    # 4. enforce NOT NULL on the three new columns
    op.alter_column("workflow_types", "category_id", nullable=False)
    op.alter_column("workflow_types", "short_name", nullable=False)
    op.alter_column("workflow_types", "long_name", nullable=False)

    # 5. FK from workflow_types.category_id -> workflow_categories.category_id
    op.create_foreign_key(
        "fk_workflow_types_category_id",
        "workflow_types",
        "workflow_categories",
        ["category_id"],
        ["category_id"],
    )

    # 6. drop the ad-hoc string column
    op.drop_column("workflow_types", "type_category")

    # 7. soft-delete on user_workflows
    op.add_column(
        "user_workflows",
        sa.Column("deleted", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )

    # 8. perf indexes
    op.create_index(
        "ix_user_workflows_group_deleted",
        "user_workflows",
        ["group_id", "deleted"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_runs_workflow_started",
        "workflow_runs",
        ["workflow_id", sa.text("started_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Reverse in opposite order
    op.drop_index("ix_workflow_runs_workflow_started", table_name="workflow_runs")
    op.drop_index("ix_user_workflows_group_deleted", table_name="user_workflows")
    op.drop_column("user_workflows", "deleted")

    # Re-add type_category as nullable, backfill, then lock down
    op.add_column(
        "workflow_types",
        sa.Column(
            "type_category",
            sa.VARCHAR(length=32),
            server_default=sa.text("'general'"),
            nullable=True,
        ),
    )

    bind = op.get_bind()
    # Map category_key back to the original string. analysis and queries
    # both collapse to 'data' (the pre-migration state).
    bind.execute(
        sa.text(
            "UPDATE workflow_types SET type_category = CASE "
            "  WHEN c.category_key = 'email' THEN 'email' "
            "  WHEN c.category_key = 'calendar' THEN 'calendar' "
            "  WHEN c.category_key IN ('analysis', 'queries') THEN 'data' "
            "  ELSE 'general' "
            "END "
            "FROM workflow_categories c "
            "WHERE workflow_types.category_id = c.category_id"
        )
    )

    op.alter_column("workflow_types", "type_category", nullable=False)

    op.drop_constraint("fk_workflow_types_category_id", "workflow_types", type_="foreignkey")
    op.drop_column("workflow_types", "long_name")
    op.drop_column("workflow_types", "short_name")
    op.drop_column("workflow_types", "category_id")

    op.drop_table("workflow_categories")

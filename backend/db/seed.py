"""Idempotent seed: inserts default data only if tables are empty."""
import asyncio

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import DEFAULT_ADMIN_PASSWORD
from backend.db.session import SqlAsyncSession
from backend.db.models import ApiGroups, ApiSettings, WorkflowTypes, User
from backend.auth.users import password_helper


WORKFLOW_TYPE_DEFAULTS = [
    {
        "type_id": 1,
        "type_name": "Email Topic Monitor",
        "type_desc": "Fetch emails from Apple Mail or Gmail, categorize by topic with AI, assess urgency, and generate an Excel report.",
        "type_category": "email",
        "default_config": {
            "service": "apple_mail",
            "account": "iCloud",
            "mailbox": "INBOX",
            "period": "last 7 days",
            "topics": [],
            "scope": "",
        },
        "required_services": ["apple_mail_mcp"],
    },
    {
        "type_id": 2,
        "type_name": "Transaction Data Analyzer",
        "type_desc": "Read transaction data from CSV/Excel, profile and filter by date, generate summary report with charts and outlier detection.",
        "type_category": "data",
        "default_config": {
            "date_range": "last 30 days",
            "key_fields": [],
            "output_format": "xlsx",
        },
        "required_services": [],
    },
    {
        "type_id": 3,
        "type_name": "Calendar Digest",
        "type_desc": "Extract calendar events, detect conflicts, assess importance, and produce a formatted digest with optional Excel report.",
        "type_category": "calendar",
        "default_config": {
            "service": "apple_calendar",
            "calendars": ["Work", "Family"],
            "days": 7,
        },
        "required_services": ["apple_calendar_mcp"],
    },
    {
        "type_id": 4,
        "type_name": "SQL Query Runner",
        "type_desc": "Execute read-only SQL queries against configured databases, analyze results with AI, and generate charts and narrative.",
        "type_category": "data",
        "default_config": {
            "database": "",
            "query": "",
            "output_format": "xlsx",
        },
        "required_services": [],
    },
]


async def _seed(session: AsyncSession):
    count = await session.scalar(select(func.count()).select_from(ApiGroups))
    if count and count > 0:
        print("[seed] Data already exists, skipping seed.")
        return

    print("[seed] Seeding default data...")

    system_group = ApiGroups(group_id=1, group_name="System")
    default_group = ApiGroups(group_id=2, group_name="Default Group")
    session.add_all([system_group, default_group])
    await session.flush()

    import uuid
    admin = User(
        user_id=1,
        id=uuid.uuid4(),
        email="admin@localhost",
        user_name="admin",
        full_name="System Administrator",
        hashed_password=password_helper.hash(DEFAULT_ADMIN_PASSWORD),
        group_id=1,
        is_active=True,
        is_superuser=True,
        is_verified=True,
        is_groupadmin=True,
        is_manager=True,
    )
    session.add(admin)

    settings = [
        ApiSettings(name="app_title", value="Local Automator"),
        ApiSettings(name="navbar_color", value="slate"),
        ApiSettings(name="instance_label", value="DEV"),
    ]
    session.add_all(settings)

    await session.commit()

    # Fix sequences after explicit ID inserts
    await session.execute(text("SELECT setval(pg_get_serial_sequence('api_users', 'user_id'), (SELECT MAX(user_id) FROM api_users))"))
    await session.execute(text("SELECT setval(pg_get_serial_sequence('api_groups', 'group_id'), (SELECT MAX(group_id) FROM api_groups))"))
    await session.commit()

    print("[seed] Default data seeded successfully.")


async def _seed_workflow_types(session: AsyncSession):
    count = await session.scalar(select(func.count()).select_from(WorkflowTypes))
    if count and count > 0:
        print(f"[seed] Workflow types already exist ({count} records), skipping.")
        return

    print(f"[seed] Seeding {len(WORKFLOW_TYPE_DEFAULTS)} workflow types...")
    for wf_data in WORKFLOW_TYPE_DEFAULTS:
        session.add(WorkflowTypes(**wf_data))
    await session.commit()
    print("[seed] Workflow types seeded successfully.")


async def run_seed():
    async with SqlAsyncSession() as session:
        await _seed(session)
    async with SqlAsyncSession() as session:
        await _seed_workflow_types(session)


def run_seed_sync():
    asyncio.run(run_seed())

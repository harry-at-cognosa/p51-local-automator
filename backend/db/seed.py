"""Idempotent seed.

Groups/admin/settings: insert only if the groups table is empty.

Workflow categories + types: upsert on every startup so that renames in
this file (short_name, long_name, type_desc, default_config, category)
propagate to the DB without manual intervention. This overwrites hand-
edits made directly in the DB to the canonical seeded rows — acceptable
for this project (local/dev). Add new types here and restart to install.
"""
import asyncio

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import DEFAULT_ADMIN_PASSWORD
from backend.db.session import SqlAsyncSession
from backend.db.models import (
    ApiGroups,
    ApiSettings,
    User,
    WorkflowCategories,
    WorkflowTypes,
)
from backend.auth.users import password_helper


WORKFLOW_CATEGORY_DEFAULTS = [
    {"category_key": "email", "short_name": "Email", "long_name": "Email", "sort_order": 10},
    {"category_key": "calendar", "short_name": "Calendar", "long_name": "Calendar", "sort_order": 20},
    {"category_key": "analysis", "short_name": "Analysis", "long_name": "Data Set Analysis", "sort_order": 30},
    {"category_key": "queries", "short_name": "Queries", "long_name": "Structured Queries", "sort_order": 40},
]


WORKFLOW_TYPE_DEFAULTS = [
    {
        "type_id": 1,
        "type_name": "Email Topic Monitor",
        "type_desc": "Fetch emails from Apple Mail or Gmail, categorize by topic with AI, assess urgency, and generate an Excel report.",
        "category_key": "email",
        "short_name": "Topic Monitor",
        "long_name": "Email Topic Monitor",
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
        "category_key": "analysis",
        "short_name": "Transactions",
        "long_name": "Transaction Data Analyzer",
        "default_config": {
            "file_path": "",
            "start_date": "",
            "end_date": "",
            "days": None,
            "key_fields": [],
        },
        "required_services": [],
    },
    {
        "type_id": 3,
        "type_name": "Calendar Digest",
        "type_desc": "Extract calendar events, detect conflicts, assess importance, and produce a formatted digest with optional Excel report.",
        "category_key": "calendar",
        "short_name": "Digest",
        "long_name": "Calendar Digest",
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
        "category_key": "queries",
        "short_name": "SQL Runner",
        "long_name": "SQL Query Runner",
        "default_config": {
            "connection_string": "",
            "query": "",
            "query_name": "query",
        },
        "required_services": [],
    },
    {
        "type_id": 5,
        "type_name": "Auto-Reply (Draft Only)",
        "type_desc": "Scan inbox for matching emails, generate an acknowledgment reply with AI, and save it to the account's Drafts folder. No email is sent automatically.",
        "category_key": "email",
        "short_name": "Draft Reply",
        "long_name": "Auto-Reply (Draft Only)",
        "default_config": {
            "account": "iCloud",
            "mailbox": "INBOX",
            "period": "last 7 days",
            "sender_filter": "",
            "body_contains": "",
            "body_email_field": "",
            "signature": "",
            "tone": "warm and professional",
            "fetch_limit": 50,
        },
        "required_services": ["apple_mail_mcp"],
    },
    {
        "type_id": 6,
        "type_name": "Auto-Reply (Approve Before Send)",
        "type_desc": "Scan inbox for matching emails, generate an acknowledgment reply with AI, and queue it in the app for human approval. User can approve, edit and send, save as draft, or reject each reply.",
        "category_key": "email",
        "short_name": "Approve Reply",
        "long_name": "Auto-Reply (Approve Before Send)",
        "default_config": {
            "account": "iCloud",
            "mailbox": "INBOX",
            "period": "last 7 days",
            "sender_filter": "",
            "body_contains": "",
            "body_email_field": "",
            "signature": "",
            "tone": "warm and professional",
            "fetch_limit": 50,
        },
        "required_services": ["apple_mail_mcp"],
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


async def _seed_workflow_categories(session: AsyncSession) -> dict[str, int]:
    """Upsert by category_key. Returns {category_key: category_id}."""
    print(f"[seed] Upserting {len(WORKFLOW_CATEGORY_DEFAULTS)} workflow categories...")
    key_to_id: dict[str, int] = {}
    for cat_data in WORKFLOW_CATEGORY_DEFAULTS:
        existing = await session.scalar(
            select(WorkflowCategories).where(WorkflowCategories.category_key == cat_data["category_key"])
        )
        if existing is None:
            row = WorkflowCategories(**cat_data)
            session.add(row)
            await session.flush()
            key_to_id[cat_data["category_key"]] = row.category_id
        else:
            existing.short_name = cat_data["short_name"]
            existing.long_name = cat_data["long_name"]
            existing.sort_order = cat_data["sort_order"]
            key_to_id[cat_data["category_key"]] = existing.category_id
    await session.commit()
    return key_to_id


async def _seed_workflow_types(session: AsyncSession, category_ids: dict[str, int]):
    """Upsert by type_name. Resolves category_id from category_key."""
    print(f"[seed] Upserting {len(WORKFLOW_TYPE_DEFAULTS)} workflow types...")
    for wf_data in WORKFLOW_TYPE_DEFAULTS:
        category_key = wf_data["category_key"]
        category_id = category_ids.get(category_key)
        if category_id is None:
            raise RuntimeError(
                f"[seed] Unknown category_key '{category_key}' for type '{wf_data['type_name']}'. "
                f"Known categories: {list(category_ids.keys())}"
            )

        row_fields = {
            "type_name": wf_data["type_name"],
            "type_desc": wf_data["type_desc"],
            "short_name": wf_data["short_name"],
            "long_name": wf_data["long_name"],
            "category_id": category_id,
            "default_config": wf_data["default_config"],
            "required_services": wf_data["required_services"],
        }

        existing = await session.scalar(
            select(WorkflowTypes).where(WorkflowTypes.type_name == wf_data["type_name"])
        )
        if existing is None:
            session.add(WorkflowTypes(type_id=wf_data["type_id"], **row_fields))
        else:
            for field, value in row_fields.items():
                setattr(existing, field, value)
    await session.commit()

    # Fix sequence after potential explicit type_id inserts
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workflow_types', 'type_id'), "
            "(SELECT MAX(type_id) FROM workflow_types))"
        )
    )
    await session.commit()
    print("[seed] Workflow types upserted successfully.")


async def run_seed():
    async with SqlAsyncSession() as session:
        await _seed(session)
    async with SqlAsyncSession() as session:
        category_ids = await _seed_workflow_categories(session)
        await _seed_workflow_types(session, category_ids)


def run_seed_sync():
    asyncio.run(run_seed())

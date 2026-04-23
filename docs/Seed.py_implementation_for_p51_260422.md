# seed.py — Bootstrap Loader Walkthrough

**Date:** 2026-04-22
**File under discussion:** `backend/db/seed.py`
**Purpose:** Explain what seed.py does, how it differs from Alembic migrations, and the implications for day-to-day platform development.

---

`seed.py` is the bootstrap loader for default data — the data the application needs to exist before anyone logs in. It runs automatically on every backend startup (from `backend/app.py:15`, called inside the FastAPI `lifespan` context manager).

## The big picture

It's split into **two distinct seeding strategies** because the data it writes has two different natures:

| Data category | Strategy | Reasoning |
|---|---|---|
| Groups, admin user, app settings | **Seed once** — if the `api_groups` table has any rows, skip the whole block | Initial-setup data. Once you've created the admin account and the two groups, the seed has done its job. You don't want it resetting the admin password or recreating groups on every restart. |
| Workflow categories + workflow types | **Upsert every startup** | These are the "catalog" — the app's declaration of what automations exist. When you edit `short_name`, `type_desc`, or `default_config` in this file and restart, those edits should propagate into the DB without any manual intervention. |

Both strategies are idempotent in the "you can run it any number of times safely" sense, but the mechanism differs.

## What it seeds

### Tier 1 — initial setup (only if `api_groups` is empty)

- **Two groups** (`_seed`, lines 145–148):
  - `group_id=1`, `"System"` — the superuser/admin group
  - `group_id=2`, `"Default Group"` — where new users land by default (see the `server_default=text("2")` on the `api_users.group_id` column in `models.py`)

- **One admin user** (lines 150–165):
  - username `admin`, email `admin@localhost`, password from `DEFAULT_ADMIN_PASSWORD` in `backend/config.py`
  - Superuser (fastapi-users flag), groupadmin, manager
  - Hard-coded `user_id=1`; fresh UUID for the fastapi-users `id` column
  - Placed in the System group

- **Three settings rows** (lines 167–172):
  - `app_title` = "Local Automator"
  - `navbar_color` = "slate" (drives the theme color gradient in the frontend)
  - `instance_label` = "DEV"

- **Sequence fix** (lines 176–179): since the groups and admin were inserted with explicit IDs, Postgres's `SERIAL` auto-increment sequences are out of sync. The `setval(pg_get_serial_sequence(...))` calls push the sequences past the max existing ID so the next insert doesn't collide.

### Tier 2 — catalog upsert (every startup, always)

- **Four workflow categories** from `WORKFLOW_CATEGORY_DEFAULTS`: `email`, `calendar`, `analysis`, `queries`
  - Upsert by unique `category_key`
  - On match, updates `short_name`, `long_name`, `sort_order` — i.e. "this file is the source of truth"

- **Six workflow types** from `WORKFLOW_TYPE_DEFAULTS`: Email Topic Monitor, Transaction Data Analyzer, Calendar Digest, SQL Query Runner, Auto-Reply (Draft Only), Auto-Reply (Approve Before Send)
  - Upsert by unique `type_name`
  - On match, updates *everything* (type_desc, category_id, short/long names, default_config, required_services) — this is the part that means **manual DB edits to any of these fields get overwritten on restart**. That's deliberate.

## The upsert pattern in detail

Look at `_seed_workflow_categories` (lines 184–203). For each category default:

```python
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
```

This is a classic "select, then insert or update" pattern. Not the fastest (two round-trips per row worst case), but 4 categories and 6 types × hundreds of ms of startup time is negligible. Returns a dict mapping `category_key` to the resolved `category_id`, which `_seed_workflow_types` then uses to fill each type's FK.

## How it connects to Alembic migrations

This is worth being clear on, because they overlap conceptually:

| Alembic | Seed |
|---|---|
| Changes the **shape** of the DB (tables, columns, indexes, constraints) | Loads **content** into that shape (rows) |
| Runs manually via `alembic upgrade head` (or in a deploy pipeline) | Runs automatically on every `uvicorn` startup |
| Each migration file runs once, tracked in `alembic_version` | No tracking — entire seed function re-runs every time |

Occasionally they overlap — the most recent migration (`a2c4e6b8d0f1`) both *adds new tables* (pending_email_replies, email_auto_reply_log) **and** inserts the two new workflow type rows in a data migration. The rows are inserted there so they exist immediately after `alembic upgrade`, and then the seed also knows about them so they stay in sync if the next startup tweaks any field. Belt and suspenders on purpose.

## Entry points

- `run_seed()` — the async entry point called from `app.py:15` during FastAPI lifespan startup
- `run_seed_sync()` — a sync wrapper that calls `asyncio.run(run_seed())`, intended for use from scripts or a hypothetical CLI (`python -m backend.db.seed`) but not wired up anywhere currently

## Practical implications you'll run into

1. **To add a 7th workflow type**, edit `WORKFLOW_TYPE_DEFAULTS` here, add the matching dispatch branch in `api/workflows.py:_run_workflow_background`, add the config UI branch in `frontend/src/components/WorkflowConfigForm.tsx`, and restart. No migration needed (unless the type requires a new table).

2. **To edit an existing type's description or config defaults**, change this file and restart. The upsert writes it through. Existing `user_workflows` rows that already reference that type are *not* modified — their `config` JSON is their own.

3. **To change an admin password**: don't do it here (this block is skipped on re-runs). Do it through the UI or a manual UPDATE.

4. **If you ever need to truly re-seed from scratch**: `TRUNCATE api_groups CASCADE` would cascade delete everything, then restart. Don't do that in production.

5. **The two-session pattern** in `run_seed()` (lines 249–254) exists because `_seed` commits the admin + groups first, then a fresh session starts for the catalog work. Mostly cosmetic — could be one session — but keeps failure blast radius smaller if the catalog half blows up.

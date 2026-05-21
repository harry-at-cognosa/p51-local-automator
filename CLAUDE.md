# Local Automator (p51)

## Project Purpose

Mac Mini server platform for small businesses (<15 users). Employees configure and run AI-powered automations — email monitoring, data analysis, calendar digests, reports — through a web interface. All processing is local except LLM API calls.

## Architecture

- **Backend:** FastAPI + SQLAlchemy async + PostgreSQL (no Docker)
- **Frontend:** React 19 + TypeScript + Vite + Bootstrap + Zustand
- **Auth:** fastapi-users + JWT (7-day tokens), roles: superuser, groupadmin, manager, employee
- **LLM:** Anthropic SDK (direct, no CrewAI)
- **Services:** Local MCP servers for Apple Mail, Apple Calendar; direct Gmail API (Track B Phase B1/B2) for Workspace email; direct Google Calendar API (Track GC) for Workspace calendar. The `gmail_accounts` table stores OAuth credentials for all Google services on a per-account basis (despite the name) — Gmail and Calendar share the same row; new services add scopes + check for them in `account.scopes`.
- **Scheduling:** APScheduler (in-process)
- **Data:** PostgreSQL for structured data, filesystem for artifacts, optional Google Sheets output

## Project Structure

- `backend/` — FastAPI application
  - `api/` — Route handlers
  - `auth/` — fastapi-users + JWT
  - `db/` — Models, schemas, session, seed, repository classes (tables/)
  - `services/` — LLM service, MCP client, workflow engine, scheduler
  - `alembic/` — Database migrations
  - `tests/` — pytest
- `frontend/` — React SPA
- `data/` — Generated artifacts: `{group_id}/{user_id}/{workflow_id}/{run_id}/`
- `mcp/` — MCP server start scripts

## Conventions

- Python 3.12+
- Async-first (SQLAlchemy async ORM, asyncpg)
- Repository pattern: `backend/db/tables/` classes encapsulate queries
- Multi-tenant: all queries filter by `group_id`
- Soft deletes: `deleted` column (0=active, 1=deleted)
- Roles: superuser > groupadmin > manager > employee
- Output files: `<file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/` (resolved per Phase 1.4 chain: group_settings → api_settings → error)
- User input files: `<file_system_root>/{group_id}/{user_id}/inputs/` — per-user sandbox surfaced to the workflow config UI by the `GET /api/v1/files/list` endpoint and the `<FilePicker>` component. Reusable across all workflows owned by that user. Type 2 ("Transaction Data Analyzer") and Type 7 ("Analyze Data Collection / AWF-1") both resolve their data files under this path with a traversal guard; absolute paths in `config.file_path` are rejected at run time. See `phase T2S` commits for the alignment work.
- Role-scope rule for run-surfacing endpoints (Dashboard stats / recent runs, Workflows list): `_run_scope_filter(user)` in `backend/api/dashboard.py` returns the where-clauses — superuser sees system-wide, groupadmin/manager sees their group, everyone else sees only workflows where `user_id == current_user`. New endpoints that list runs or workflows should reuse this helper rather than hardcoding `group_id == user.group_id`.
- `workflow_types.schedulable` (added in A1.1, default TRUE): per-type flag. FALSE for cron-incompatible types (e.g. AWF-1 "Analyze Data Collection" — too expensive/slow to fire from cron). Frontend hides schedule UI when false.
- New workflow types should ship with a populated `config_schema` and let the schema-driven `SchemaConfigForm` render their config UI rather than adding another typeId branch in `WorkflowConfigForm.tsx`. Types 1–6 keep their hand-tuned forms; AWF-1 (type 7) is the first schema-only type.
- `workflow_runs.archived` (added in M.1): set TRUE by the archive sweep to hide runs from non-superuser read paths. Every run-surfacing query must filter `archived = false` unless the caller is superuser AND opts in (`?include_archived=true` on the list/runs endpoints). Purge ignores the flag and hard-deletes. Admin UI lives at `/app/admin/maintenance`; audit history in the `maintenance_log` table.

## Database

- PostgreSQL, database name: `p51_automator`
- Migrations via Alembic: `alembic upgrade head`
- Seed on startup (idempotent)

## Workflow limits

All numeric workflow caps resolve through `resolve_int_setting()` in `backend/services/workflow_engine.py` with a 3-layer chain: `workflow.config[<key>]` → `group_settings(group_id, <key>)` → `api_settings(<key>)` → runner-local fallback. Each key is exported as a `SETTING_*` constant in the same file. Defaults are seeded by Alembic migration `e1f3b2a8d6c5_seed_workflow_limit_defaults.py`.

| Setting key | Default | Used by | Meaning |
|---|---|---|---|
| `email_fetch_limit` | 100 | Types 1, 5, 6 | Max messages fetched per account per run |
| `analyzer_timeout_seconds` | 120 | Type 2 | Subprocess timeout for the analyzer script |
| `analyzer_llm_sample_rows` | 50 | Type 2 | Rows handed to the LLM for narrative |
| `analyzer_text_truncate_chars` | 8000 | Type 2 | Profile + summary text caps before LLM |
| `sql_llm_sample_rows` | 50 | Type 4 | Rows handed to the LLM for narrative |
| `sql_row_limit` | (none) | Type 4 | Hard cap on total result rows; blank = no cap |
| `reply_max_candidates` | 20 | Types 5, 6 | Max replies drafted per run |
| `analyze_max_agent_turns` | 25 | Type 7 | Agent loop turns in the analyze stage |
| `audit_max_agent_turns` | 12 | Type 7 | Agent loop turns in the audit stage |
| `llm_max_tokens` | 4096 | Type 7 | Per-call max_tokens for every LLM-bearing stage |
| `step_summary_truncate_chars` | 2000 | Type 7 | Step output truncation |

**Absolute ceilings** live in code as runaway-cost guards and cannot be exceeded via api_settings: `ABS_MAX_AGENT_TURNS = 100`, `ABS_MAX_LLM_TOKENS = 16384` in `workflow_engine.py`. Values above these are silently clamped at run time. Bump only by editing source.

**Operator tuning:** superuser edits `api_settings` defaults at `/app/admin/settings`; groupadmin sets per-group overrides at `/app/admin/group-settings`; user sets per-workflow overrides via the "Advanced" section on each workflow type's config form.

## Versioning

- **Scheme:** CalVer `YYYY.MM.DD.N` (e.g. `2026.05.18.0`, `2026.05.18.1`, `2026.05.19.0`). The trailing `N` is a per-day serial that resets to 0 each new day. Date is zero-padded so the format also string-sorts correctly.
- **Single source of truth:** `backend/__init__.py` `__version__`. `frontend/package.json` `version` is bumped in lockstep manually. FastAPI metadata, `/api/v1/system/version`, and any future UI footer read from `__version__`.
- **Bump rule:** every commit on `main` that ships user-visible code or a migration gets a new version. The date portion always matches today; `N` increments per qualifying push that day. Skip the bump for doc-only, comment-only, or test-only commits. New day → `N` resets to 0.
- **DB schema version:** Alembic revision hash. Latest defined head lives in `backend/alembic/versions/`; what's applied is in the DB's `alembic_version` table. The app logs an `alembic_revision_mismatch` warning at startup if the two diverge, and `/api/v1/system/version` returns both fields side-by-side for triage.
- **Multi-machine deploy check:** after pulling code, run `alembic upgrade head` then restart `uvicorn`. Confirm via `curl http://localhost:8000/api/v1/system/version` — `db_revision` should equal `expected_db_revision`.

## Running

```bash
# Backend
cd p51-local-automator
pip install -r backend/requirements.txt
createdb p51_automator
alembic upgrade head
python3 -m uvicorn backend.main:app --reload --port 8000

# Frontend (dev)
cd frontend
npm install
npm run dev
```

## Inherited From

- **CompIntelMon** (`/Users/harry/compintelmon_code`) — app factory, auth, multi-tenant, DB patterns
- **51_project_simple_agentic_automation** — email/calendar skills, Excel styling, MCP integration patterns

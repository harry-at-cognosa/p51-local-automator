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

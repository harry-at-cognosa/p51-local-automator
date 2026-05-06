# Local Automator (p51)

## Project Purpose

Mac Mini server platform for small businesses (<15 users). Employees configure and run AI-powered automations — email monitoring, data analysis, calendar digests, reports — through a web interface. All processing is local except LLM API calls.

## Architecture

- **Backend:** FastAPI + SQLAlchemy async + PostgreSQL (no Docker)
- **Frontend:** React 19 + TypeScript + Vite + Bootstrap + Zustand
- **Auth:** fastapi-users + JWT (7-day tokens), roles: superuser, groupadmin, manager, employee
- **LLM:** Anthropic SDK (direct, no CrewAI)
- **Services:** Local MCP servers for Apple Mail, Apple Calendar; direct Gmail API (Track B Phase B1) for Workspace email; Google Workspace MCP for calendar (TBD).
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
- User input files: `<file_system_root>/{group_id}/{user_id}/inputs/` — per-user sandbox surfaced to the workflow config UI by the `GET /api/v1/files/list` endpoint and the `<FilePicker>` component. Reusable across all workflows owned by that user.

## Database

- PostgreSQL, database name: `p51_automator`
- Migrations via Alembic: `alembic upgrade head`
- Seed on startup (idempotent)

## Running

```bash
# Backend
cd p51_local_automator
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

# Local Agentic Automation Platform — Full Plan

## Context

What started as a CLI demo project has evolved into a bigger vision: a **Mac Mini server platform for small businesses (<15 users)** that provides employee-configurable AI-powered automations — email monitoring, data analysis, calendar management, report generation, and multi-step workflows.

### Key Constraints
- **Fully local** (except LLM API calls to Claude or local Ollama)
- **No cloud proxies** — local MCP servers for Apple and Google services
- **Multi-user** — employees configure and use their own automations against their own accounts
- **FastAPI + React + PostgreSQL** — same proven stack as CompIntelMon
- **No Docker** — bare metal Mac Mini deployment
- **Support both Apple and Google services** — each user chooses per workflow

### Decisions Made
- **Phase 1 first:** Install local MCP servers + fix CLI skills as immediate proof of concept, then build the web app
- **New project directory:** Fresh start (separate from this demo project), porting proven scripts/skills
- **Dual service support:** Both Apple (Mail.app, Calendar.app) and Google Workspace (Gmail, Drive, Sheets, Calendar) via local MCP servers

### Reference Projects
- **CompIntelMon** (`/Users/harry/compintelmon_code`) — infrastructure blueprint for FastAPI + React + PostgreSQL + multi-tenant auth + async agents
- **This demo project** (`51_project_simple_agentic_automation`) — proven skills, scripts, and MCP integration patterns

---

## Phase 1: Local MCP Servers + CLI Skills — COMPLETED

**What was done:**
1. Installed `@griches/apple-mail-mcp` and `@griches/apple-calendar-mcp` as local MCP servers in Claude Code (npx, stdio transport)
2. Updated `/check-email` skill to use local Apple Mail MCP instead of Anthropic's Gmail proxy
3. Created `/list-events` skill using local Apple Calendar MCP
4. Tested both against real data (iCloud, cognosa.net Gmail, Work/Family calendars)
5. Styled Excel output (Calisto MT font, 130% zoom, 26px rows, windowed)
6. Google Workspace MCP (`taylorwilsdon/google_workspace_mcp`) identified but not yet installed — requires Google Cloud OAuth setup

**What we proved:**
- Local MCP servers are fast, reliable, no cloud dependency
- Apple Mail MCP reads from all accounts configured in Mail.app
- Apple Calendar MCP reads from all iCloud/Exchange calendars
- The skill pattern (Claude as agent + MCP tools + Python scripts for output) works well

---

## Phase 2: New Project + Foundation Web App

**Goal:** Standing FastAPI + React app with auth, adapted from CompIntelMon.

### Steps
1. Create new project directory (confirm location with Harry)
2. Fork/adapt CompIntelMon's backend structure:
   - `backend/app.py`, `auth/`, `config.py`, `db/session.py`
   - Simplify roles to: admin, manager, employee
   - New models: `workflow_types`, `user_workflows`, `workflow_runs`, `workflow_steps`, `workflow_artifacts`
3. Fork/adapt frontend: Login, Dashboard, basic nav
4. Set up PostgreSQL database + Alembic migrations
5. Seed `workflow_types` with the initial automation types
6. Port proven scripts from demo project: `analyze_data.py`, `email_to_excel.py`

---

## Phase 3: Workflow Engine + LLM Service

**Goal:** Backend can execute multi-step workflows with LLM judgment.

1. `services/llm_service.py` — Anthropic SDK wrapper for structured judgment calls
2. `services/mcp_client.py` — Calls local MCP servers programmatically
3. `services/workflow_engine.py` — Executes workflow steps, saves state after each, supports pause/resume
4. API endpoints: create workflow, trigger run, get results
5. Implement Email Topic Monitor as first workflow type

---

## Phase 4: Remaining Workflow Types + Scheduling

1. Transaction Data Analyzer workflow (adapt existing `analyze_data.py`)
2. Calendar Digest workflow
3. SQL Query Runner workflow
4. APScheduler integration for per-user schedules

---

## Phase 5: Frontend Workflows UI

1. Workflow catalog page (browse available types)
2. Workflow configuration wizard (per-type config forms)
3. Run history + results viewer
4. Artifact viewer (Excel preview, chart display, markdown reports)
5. Schedule management

---

## Phase 6: Mac Mini Deployment + Hardening

1. Set up Mac Mini with PostgreSQL, Python, Node
2. Configure Mail.app + Calendar.app accounts
3. Google OAuth credentials for Workspace MCP
4. launchd for app auto-start
5. HTTPS via Caddy or nginx reverse proxy
6. Backup strategy for PostgreSQL + data/

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  React Frontend (Vite + TypeScript + Bootstrap)          │
│  - Dashboard, Workflow Config, Results Viewer, Chat      │
└────────────────────┬─────────────────────────────────────┘
                     │ axios (JWT)
┌────────────────────▼─────────────────────────────────────┐
│  FastAPI Backend (:8000)                                 │
│  ├─ API routers (auth, users, workflows, results, chat)  │
│  ├─ Workflow engine (multi-step pipelines + checkpoints)  │
│  ├─ LLM service (Anthropic SDK / Ollama)                 │
│  ├─ APScheduler (per-user scheduled workflows)           │
│  └─ MCP client (calls local MCP servers for tools)       │
└──┬──────────┬──────────┬─────────────────────────────────┘
   │          │          │
   ▼          ▼          ▼
PostgreSQL  Local MCP   Claude API
            Servers     (or Ollama)
   ┌────────┴────────┐
   │  Apple MCP      │  Google Workspace MCP
   │  (Mail,Calendar) │  (Gmail,Drive,Sheets,
   │  @griches/*     │   Calendar,Docs)
   │                 │  taylorwilsdon/
   │                 │  google_workspace_mcp
   └─────────────────┘
```

## What We Reuse from CompIntelMon

| Component | CompIntelMon | This Project |
|---|---|---|
| App factory | `backend/app.py` | Same pattern |
| Auth | fastapi-users + JWT + roles | Same, adapt roles to: admin, manager, employee |
| Multi-tenant | group_id scoping | Same — groups = companies/teams |
| DB layer | SQLAlchemy async + repository pattern | Same |
| Migrations | Alembic | Same |
| Scheduling | APScheduler (in-process) | Same, but per-user workflow schedules |
| Agents | CrewAI + Anthropic | Replace CrewAI with direct Anthropic SDK (simpler, fewer deps) |
| Frontend | React 19 + Bootstrap + Zustand | Same stack |
| Config | .env + db settings | Same |
| Data storage | JSON files on disk + DB metadata | Same hybrid approach |

## Database Schema

```
api_groups          -- tenant (company/team)
api_users           -- users with roles (admin, manager, employee)
api_settings        -- global system settings
group_settings      -- per-group settings

workflow_types      -- catalog of available automations
  - type_id, type_name, type_desc, type_category
  - default_config (JSON), required_services (JSON)

user_workflows      -- user-configured workflow instances
  - workflow_id, user_id, group_id, type_id
  - name, config (JSON), schedule (JSON), enabled, last_run_at

workflow_runs       -- execution history
  - run_id, workflow_id, started_at, completed_at
  - status (running, paused, completed, failed)
  - current_step, total_steps, trigger (manual, scheduled, webhook)

workflow_steps      -- per-step results within a run
  - step_id, run_id, step_number, step_name
  - status, started_at, completed_at
  - output_summary, artifacts (JSON), llm_tokens_used, error_detail

workflow_artifacts  -- generated files
  - artifact_id, run_id, step_id
  - file_path, file_type, file_size, description

conversations       -- ad-hoc chat per workflow
conversation_messages
```

## Workflow Types (Initial Catalog)

1. **Email Topic Monitor** — Fetch emails → LLM categorizes → Excel report
2. **Transaction Data Analyzer** — Profile data → LLM selects fields → Charts + report
3. **Calendar Digest** — Fetch events → LLM assesses importance → Formatted digest
4. **SQL Query Runner** — Execute query → LLM interprets → Charts + narrative
5. **Multi-Step Workflows** — Chain any of the above with approval gates

## Project Structure

```
project_root/
├── backend/
│   ├── main.py
│   ├── app.py                    # FastAPI factory
│   ├── config.py                 # .env loading
│   ├── auth/                     # fastapi-users + JWT
│   ├── api/                      # Route handlers
│   │   ├── auth.py, users.py, groups.py
│   │   ├── workflows.py          # Workflow CRUD + trigger
│   │   ├── runs.py               # Run history + results
│   │   ├── artifacts.py          # File downloads
│   │   ├── conversations.py      # Ad-hoc chat
│   │   ├── dashboard.py
│   │   └── settings.py
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models
│   │   ├── schemas.py            # Pydantic schemas
│   │   ├── session.py            # Async/sync engines
│   │   ├── seed.py               # Workflow types + admin user
│   │   └── tables/               # Repository classes
│   ├── services/
│   │   ├── llm_service.py        # Anthropic SDK / Ollama
│   │   ├── mcp_client.py         # Local MCP server calls
│   │   ├── workflow_engine.py    # Step execution + checkpointing
│   │   ├── scheduler_service.py  # APScheduler
│   │   └── workflows/            # Per-type workflow logic
│   │       ├── email_monitor.py
│   │       ├── data_analyzer.py
│   │       ├── calendar_digest.py
│   │       └── sql_runner.py
│   ├── tests/
│   └── alembic/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Workflows.tsx       # Browse + configure
│   │   │   ├── WorkflowDetail.tsx  # Config + run history
│   │   │   ├── RunDetail.tsx       # Step results + artifacts
│   │   │   └── admin pages...
│   │   ├── components/
│   │   ├── stores/
│   │   └── api/
│   └── package.json
├── data/                          # Workflow output files
│   └── {group_id}/{user_id}/{workflow_id}/{run_id}/
├── mcp/                           # MCP server configs/scripts
│   ├── start_apple_mcp.sh
│   └── start_google_mcp.sh
├── .env
├── alembic.ini
└── CLAUDE.md
```

## Data Storage Strategy (Three-Tier Hybrid)

**PostgreSQL** (structured, queryable):
- User accounts, roles, group membership
- Workflow configurations, run history, artifact metadata
- All settings (per-user, per-group, system-wide)

**Local file system** (generated artifacts):
- Excel reports, charts (PNG), JSON intermediate data, markdown summaries
- Organized as `data/{group_id}/{user_id}/{workflow_id}/{run_id}/`

**Google Sheets** (optional output destination):
- Via `google_workspace_mcp` Sheets tools
- Per-workflow config choice: output to local Excel, Google Sheet, or both

## Python Packages

**From CompIntelMon (proven):** fastapi, uvicorn, fastapi-users[sqlalchemy], sqlalchemy[asyncio], asyncpg, psycopg2-binary, alembic, apscheduler, python-dotenv, structlog, pydantic

**New:** anthropic, httpx, pandas, openpyxl, matplotlib, PyYAML

**Not needed:** crewai, crawl4ai, playwright, feedparser, praw

## Verification Plan

- **Phase 2:** Login, create user, verify auth flow works
- **Phase 3:** Trigger email monitor workflow via API, verify JSON output + Excel generation
- **Phase 4:** Each workflow type produces correct output
- **Phase 5:** Full browser walkthrough: login → configure workflow → run → view results
- **Phase 6:** Mac Mini running 24/7, scheduled workflows firing, results accessible over LAN

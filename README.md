# p51-local-automator

A Mac-based automation platform for small businesses (<15 users). Employees configure and run AI-powered workflows — email monitoring, data analysis, calendar digests, report generation — through a web interface. All processing runs locally except LLM API calls.

## Why "local"?

No cloud proxies, no third-party middleware. The platform connects directly to Apple Mail, Apple Calendar, and Google Workspace services via local MCP servers running on the same machine. Your data never passes through intermediary services.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL |
| Frontend | React 19, TypeScript, Vite, Bootstrap 5, Zustand |
| Auth | fastapi-users + JWT (7-day tokens) |
| LLM | Anthropic Claude API (direct SDK, prompt caching) |
| Services | Local MCP servers — Apple Mail, Apple Calendar (Google Workspace planned) |
| Scheduling | APScheduler (in-process) |
| Migrations | Alembic |

## Workflow Types

- **Email Topic Monitor** — fetch from Mail.app via MCP, categorize with AI, generate Excel report
- **Transaction Data Analyzer** — profile CSV/Excel data, filter, chart, detect outliers
- **Calendar Digest** — fetch events, detect conflicts, assess importance with AI
- **SQL Query Runner** — execute read-only queries, analyze results with AI

## Requirements

- macOS (tested on macOS 15 / Sequoia)
- Python 3.12+
- Node.js 18+
- PostgreSQL 14+
- Anthropic API key
- Apple Mail and/or Calendar configured with accounts to monitor

## Setup

```bash
# Clone
git clone https://github.com/harry-at-cognosa/p51-local-automator.git
cd p51-local-automator

# Database
createdb p51_automator

# Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Backend dependencies
pip install -r backend/requirements.txt

# Environment config
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY

# Migrations + seed
alembic upgrade head

# Frontend
cd frontend
npm install
npm run build
cd ..

# Run (always activate venv first)
source venv/bin/activate
python3 -m uvicorn backend.main:app --port 8000
# Browse to http://localhost:8000/app
# Login: admin / admin
```

## MCP Servers

The platform uses local MCP (Model Context Protocol) servers to access Apple and Google services. These run as subprocesses — no manual startup needed.

### Included

| Server | Package | Services | Source |
|---|---|---|---|
| Apple Mail | `@griches/apple-mail-mcp` | Search, read, send email via Mail.app | [GitHub](https://github.com/griches/apple-mcp) |
| Apple Calendar | `@griches/apple-calendar-mcp` | List, search, create events via Calendar.app | [GitHub](https://github.com/griches/apple-mcp) |

### Planned

| Server | Package | Services | Source |
|---|---|---|---|
| Google Workspace | `workspace-mcp` (taylorwilsdon) | Gmail, Drive, Sheets, Calendar, Docs + 7 more | [GitHub](https://github.com/taylorwilsdon/google_workspace_mcp) |

### Prerequisites

- `npx` must be available (comes with Node.js)
- Apple Mail and Calendar must be configured with the accounts you want to monitor
- Google Workspace MCP requires a Google Cloud project with OAuth 2.0 credentials (one-time setup)

## Roles

| Role | Access |
|---|---|
| Employee | View dashboard, run own workflows |
| Manager | + create/configure workflows |
| Group Admin | + manage users and group settings |
| Superuser | + manage groups, global settings, scheduler |

## Project Origin

Built as part of an education-first exploration of agentic AI capabilities, evolving from CLI-based Claude Code skills into a full web application. Some infrastructure and application design patterns adapted from [compintelmon](https://github.com/harry-at-cognosa/compintelmon) (competitive intelligence monitoring platform) and from [cognosa-web-app](https://github.com/harry-at-cognosa/cognosa-web-app) (a multi-tenant AI / RAG as a service platform).

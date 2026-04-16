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

# Backend
pip install -r backend/requirements.txt
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY

# Migrations + seed
alembic upgrade head

# Frontend
cd frontend
npm install
npm run build
cd ..

# Run
python3 -m uvicorn backend.main:app --port 8000
# Browse to http://localhost:8000/app
# Login: admin / admin
```

## MCP Servers (optional, for email/calendar workflows)

```bash
# These run automatically when workflows trigger — no manual setup needed.
# Ensure npx is available (comes with Node.js).
# Apple Mail and Calendar must be configured in Mail.app / Calendar.app.
```

## Roles

| Role | Access |
|---|---|
| Employee | View dashboard, run own workflows |
| Manager | + create/configure workflows |
| Group Admin | + manage users and group settings |
| Superuser | + manage groups, global settings, scheduler |

## Project Origin

Built as part of an education-first exploration of agentic AI capabilities, evolving from CLI-based Claude Code skills into a full web application. Some infrastructure and application design patterns adapted from [compintelmon](https://github.com/harry-at-cognosa/compintelmon) (competitive intelligence monitoring platform) and from [cognosa-web-app](https://github.com/harry-at-cognosa/cognosa-web-app) (a multi-tenant AI / RAG as a service platform).

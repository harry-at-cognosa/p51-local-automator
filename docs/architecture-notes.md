# Architecture Notes

## Decision: Education-First, CLI-Native Approach

**Date:** 2026-04-11

We evaluated four deployment architectures and decided to **defer the app architecture decision** in favor of an education-first approach: build all automations as native Claude Code artifacts (skills, agents, hooks, triggers) first, then wrap in an app layer once we understand all the pieces.

---

## Architectures Evaluated

### 1. Multi-User Server App (FastAPI + PostgreSQL + React)
- **Pros:** Role-based access, shared scheduling, centralized config, polished demo
- **Cons:** Highest dev effort (~3-4 weeks MVP), requires server/cloud, ops burden
- **Verdict:** Best for production team deployment. Deferred to Phase 5.

### 2. Desktop/Single-User (Node.js + SQLite + Browser UI)
- **Pros:** Zero infrastructure, instant startup, perfect for laptop demos
- **Cons:** No multi-user, no remote access, scheduling depends on machine staying on
- **Verdict:** Too limited for the team deployment goal.

### 3. CLI-First with Optional Web Dashboard
- **Pros:** Fastest to build, each automation is a standalone script, showcases Claude Code directly
- **Cons:** Less polished for non-technical audiences
- **Verdict:** This is essentially what we're doing in Phases 2-4.

### 4. Hybrid: Shared Core + Swappable Interface (Recommended for Phase 5)
- **Pros:** Build once, deploy as CLI or server app. SQLite for dev, Postgres for team. Same automation logic reused.
- **Cons:** Requires upfront design discipline to keep core independent of interface
- **Verdict:** Recommended architecture for Phase 5 when we add the app layer.

---

## Phase 5 Architecture Plan (Deferred)

When we're ready to add the app layer, the architecture will be:

```
project/
  core/              # Pure automation logic (migrated from scripts/agents/)
    agents/           # Agent implementations
    services/         # Google Sheets, Excel, email, DB integrations
    models/           # Pydantic models
    storage/          # Abstract repo + SQLite/Postgres implementations
  api/                # FastAPI -- thin adapter calling core/
  cli/                # CLI entry points -- thin adapter calling core/
  web/                # React + Vite + Tailwind frontend
  config/             # Per-client YAML configs
  output/             # Per-user artifact storage
```

### Technology Stack (Phase 5)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Core logic | Python 3.12+ | Best Claude Code SDK support, pandas/openpyxl |
| API | FastAPI | Async, auto-docs, lightweight |
| DB (single-user) | SQLite via aiosqlite | Zero config |
| DB (team) | PostgreSQL via asyncpg | Concurrent, production-grade |
| DB abstraction | SQLAlchemy 2.0 async | Swap engines via config line |
| Frontend | React + Vite + Tailwind | Fast to build |
| Scheduling | Claude Code triggers + APScheduler | Showcases platform + fallback |
| Auth (team) | JWT with role claims | Minimal but sufficient |
| Artifacts | Local filesystem, per-user subdirs | Simple, inspectable |

### Key Design Rule
Everything in `core/` imports nothing from `api/`, `cli/`, or `web/`. The interface layers are thin adapters.

### Per-Client Customization
Each client gets a YAML config file. In single-user mode: file on disk. In multi-user mode: stored in database, editable via web UI. No code changes per client.

---

## Why This Order Matters

By building automations as Claude Code native artifacts first (Phases 2-4), we:
1. **Learn the capabilities** -- understand exactly what skills, agents, hooks, and triggers can do
2. **Have working logic** -- the automation code exists and is tested before we wrap it
3. **Make informed architecture decisions** -- we'll know what the app layer actually needs to support
4. **Can demo immediately** -- each phase produces something runnable, not "wait until the full stack is done"

# Deployment Topology Notes

**Date:** 2026-04-22
**Context:** Clarifying where application components live across the two deployment modes p51-local-automator is designed for: desktop (everything on one box) and SOHO (small office, Mac Mini as the shared server).

## The two deployment modes

| Mode | Description | Host running uvicorn |
|---|---|---|
| **Desktop / all-in-one** | A single developer or user machine runs the database, the backend, and accesses the frontend from the same box. Current state of Harry's dev setup. | The desktop itself |
| **SOHO / Mac Mini as server** | A Mac Mini (or similar always-on box) runs Postgres + uvicorn + MCP subprocesses. Other people in the office point their browsers at it over the local network. <15 users. | The Mini |

Both modes run the same single uvicorn process. There is no separate "web server" + "backend" split. uvicorn serves both the JSON API (`/api/v1/*`) and the compiled frontend (`/app/*`) from one port.

## Where each component lives

Regardless of mode, all paths below are **on the host running uvicorn** (desktop or Mini — same layout, just different machine).

| Component | Location |
|---|---|
| Structured data (workflows, runs, users, settings, artifacts metadata) | PostgreSQL database `p51_automator`, local to the host (port 5432) |
| Run artifacts (Excel reports, charts, JSON, PNGs) | `<app_root>/data/{group_id}/{user_id}/{workflow_id}/{run_id}/` on the host's filesystem |
| Compiled frontend bundle | `<app_root>/backend/static/` (product of `npm run build`) |
| Secrets + config | `<app_root>/.env` |
| App logs | Uvicorn stdout/stderr (no file logger configured by default) |
| Alembic migration history | `alembic_version` table in Postgres + `.py` files under `backend/alembic/versions/` |
| JWT session state | In the browser's localStorage on each user's machine. Nothing persistent on the server. |

**The `data/` folder is always under the app root on the host running the backend.** Nothing about `data/` changes between desktop and SOHO mode — only which machine it's on.

## How users reach artifacts

- **Desktop mode:** the person running the app can open `data/.../run_id/` directly in Finder. The in-app Download button also works. Either is fine.
- **SOHO mode:** users on other machines cannot see the Mini's filesystem. The **only** way they get artifact files is via the in-app Download button on the Run Detail page, which calls `GET /api/v1/artifacts/{artifact_id}/download` with their JWT, authorizes by `group_id`, and streams the file to their browser's download folder.

Keeping artifact access behind the download endpoint is deliberate — it enforces per-group authorization. Exposing `data/` directly via SMB/AFP/WebDAV would bypass that check (a user could fetch another user's run output).

## What SOHO does NOT need

My earlier explanation mentioned nginx, CDN, and separate database hosts. That was over-engineering for this project. For <15 users on a Mac Mini:

- **No nginx/reverse proxy.** Uvicorn handles the traffic directly on whatever port you pick (8001 in dev). If you want HTTPS on the local network later, Caddy or Tailscale are lighter-weight than nginx.
- **No CDN.** Static assets are served from `backend/static/` by the same uvicorn. There's no latency problem to solve at this scale.
- **No separate database host.** Postgres runs on the Mini next to uvicorn.
- **No shared storage service.** `data/` is just a folder on the Mini's internal disk. Back it up with Time Machine like any other folder.

Those pieces matter for multi-tenant SaaS deployments with hundreds of concurrent users. They add cost and ops overhead that a SOHO deployment shouldn't carry.

## Network access in SOHO mode

Clients reach the Mini via whatever hostname/IP the LAN provides. Typical options:

- `http://mac-mini.local:8001/app` (mDNS / Bonjour, works out of the box on Apple networks)
- `http://192.168.x.x:8001/app` (static IP on the router)
- Over Tailscale or a VPN if remote access is desired

CORS isn't an issue because the frontend is served from the same origin as the API (both come off uvicorn).

## Backup implications

In SOHO mode, backing up the Mini captures the whole platform:

1. `pg_dump p51_automator > backup.sql` — database
2. `tar -czf data.tgz <app_root>/data/` — artifacts
3. `cp <app_root>/.env .env.backup` — secrets

Or just let Time Machine back up `<app_root>` and the Postgres data directory. The app holds no state outside those locations.

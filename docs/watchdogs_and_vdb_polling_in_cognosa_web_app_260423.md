# Watchdogs and VDB / LLM Polling in cognosa_web_app

**Date:** 2026-04-23
**Purpose:** Explain the watchdog pattern used in `~/cognosa_web_app`, how it tracks multiple `run_tasks.py` processes, and how the related-but-distinct Vector DB and LLM availability polling fits into the same module. Written as reference for p51_local_automator — none of this is in p51 today, but the patterns would port cleanly if/when we add out-of-process workers or external-service health monitoring.

---

## Three senses of "watchdog" — definitions first

Before diving into cognosa, the word "watchdog" has three distinct meanings. Worth disambiguating because cognosa uses one of them (the custom heartbeat pattern) and the generic term can mean any:

1. **Python `watchdog` library** — a filesystem event monitor (inotify / FSEvents wrapper). Not used in cognosa. Commonly pulled in via `uvicorn[standard]` when you run with `--reload`.
2. **Process supervisor** — OS-level tools like `systemd`, `launchd`, `supervisord` that restart crashed processes. Also not the cognosa pattern; would live outside the Python code entirely.
3. **Application-level heartbeat / dead-man's-switch** — the pattern cognosa implements. A long-running process writes periodic "I'm alive" markers to a database table; other parts of the system read those markers to know who's alive and who's stale.

The rest of this doc is about sense #3.

---

## The cognosa pattern: `common/watchdogs/`

One folder, ~six files, does the whole job. Key pieces:

### The `api_processes` table

One row per *named process / subprocess*, keyed on `(ap_name, ap_subname)`, holding:

- `ap_type` (e.g. `'run_tasks'`) — which class of process
- `ap_name` (e.g. `'run_tasks_primary'`, `'run_tasks_secondary_1'`) — which instance
- `ap_subname` (e.g. `'watchdog'`, `'polling_loop'`, `'vdb_p_1'`, `'vdb_llm_checking'`) — which component inside that instance
- `ap_status` (free-text, `'running'`, `'exit'`, `'starting'`, etc.)
- `ap_updated_at` (last heartbeat timestamp) — `now()` on every upsert
- `ap_json` (optional JSON blob for structured telemetry)

### `ApiProcessesTable.upsert_api_process()`

Postgres `INSERT ... ON CONFLICT DO UPDATE` on the unique constraint `(ap_name, ap_subname)`. Always bumps `ap_updated_at = now()`. This is what a heartbeating worker calls every few seconds.

### `ApiProcessesTable.check_exists_running(ap_name, max_before)`

Queries "is there a row for this `ap_name` where `ap_updated_at >= now() - max_before` and `ap_status != 'exit'`?" Used two ways:

1. **Startup safety** — `check_name_is_still_running()` in `common/watchdogs/__init__.py`. Called at `run_tasks.py` boot. If another process with the same name has pinged within `AP_MAX_BEFORE` seconds, the new instance logs an error and exits. Prevents accidental double-starts.
2. **Status dashboard** — the admin "server status" page reads the same query to decide whether a given process is fresh or stale.

### `WatchdogThread`

`backend/common/watchdogs/watchdog_thread.py` — a `threading.Thread` subclass whose whole purpose is to emit a heartbeat. Its `run()` loop:

```python
while self._is_running:
    with self.sessionmaker() as session:
        ApiProcessesTable(session).upsert_api_process(
            ap_type='run_tasks',
            ap_name=self.ap_name,
            ap_subname=self.ap_subname,  # default 'watchdog'
            ap_status='running'
        )
    sleep(AP_SLEEP_TIME)     # 5.0 seconds
```

Any process that wants to show up in the health dashboard constructs a `WatchdogThread(ap_type=..., ap_name=...)`, calls `.start()`, and goes off to do its real work. On shutdown, `.stop()` + `.join()`.

### Key constants

In `common/watchdogs/__init__.py`:

- `AP_SLEEP_TIME = 5.0` — how often heartbeats refresh
- `AP_MAX_BEFORE = 10.0` — how long a row is considered "fresh" (2× the heartbeat interval gives slack for a slow cycle)

Anywhere else in the code that wants to know "is X still alive" uses those same constants so there's one place to tune the sensitivity.

---

## How `run_tasks.py` uses all this

`run_tasks.py` is a **standalone Python process**, separate from the FastAPI uvicorn process. It's the worker that actually executes LLM inference and Vector DB document tasks. Multiple instances can run concurrently on the same box:

- `run_tasks_primary` — default, no CLI args
- `run_tasks_secondary_N` — launched with `-s N` (see `tasks_lib/cmd_line_opts.py`)

`AP_NAME` is computed from the secondary flag. You can't accidentally double-start `run_tasks_primary` because of the `check_name_is_still_running` guard.

Each instance (see `run_tasks.py:27` — the `RunTasks.__init__`) spawns several heartbeating components, each with its own `ap_subname`:

| Component | `ap_subname` | Kind | Purpose |
|---|---|---|---|
| `WatchdogThread` | `watchdog` | `threading.Thread` | Pure "I'm alive" heartbeat for this whole process |
| Main polling loop | `polling_loop` | Main thread | Pulls tasks off the queue and dispatches them; heartbeats as it goes |
| `VDBWorker` × N | `vdb_p_1`, `vdb_p_2`, … | `multiprocessing.Process` | Execute individual VDB document tasks (embedding, upsert, retrieval). True OS subprocesses so one crashing doesn't bring the parent down. Each heartbeats from within its loop. |
| `VDBLLMStatusWorker` | `vdb_llm_checking` | `threading.Thread` (primary only) | External-service health probe — described separately below |

So a single `run_tasks_primary` writes at least 4 rows into `api_processes`: its own watchdog, its polling loop, N rows for the VDB subprocesses, and the VDB/LLM status worker. A secondary instance writes all of those except the status worker (which only runs on primary — we only need one health probe regardless of how many task processors we've scaled to).

---

## The VDB and LLM availability polling

This is the "something else" that's *related* to watchdogs but conceptually distinct — it polls **external dependencies** (Chroma/Qdrant servers, LLM API endpoints) rather than our own processes.

### `VDBLLMStatusWorker`

Lives in `backend/tasks_lib/vdb_llm_status_worker.py`. A Thread that runs only inside the primary `run_tasks` instance. Every `AP_SLEEP_TIME` (5s) seconds:

1. **For each enabled `group_vdbs` row** (VDB server configured for a group):
   - Construct a `VectorDBOps` for its `gvdbs_type` + `gvdbs_url`
   - Call `check_url()` — HTTP HEAD / handshake to the server
   - Call `collection_exists(gvdbs.gvdbs_collection)` — verify the expected collection is there
   - Write `gvdbs_status` + `gvdbs_status_text` back to the row:
     - `success` / `'Ready'`
     - `warning` / `'ChromaDB not checked due to memory leak'` (special case)
     - `danger` / `'Wrong server URL'` | `'Server not found'` | `'Collection not found'`

2. **For each enabled `group_llms` row** (LLM endpoint):
   - Check if it's a public API (OpenAI, Claude, etc.) — if yes and it was checked within the last 5 minutes, skip (`is_need_to_check_llm`). Public APIs are rarely down and calls cost money.
   - Otherwise construct `LLMOps` and call `check_working()`
   - Write `gllms_status` + `gllms_status_text` the same way

### Why this lives in `common/watchdogs/`

The folder doesn't only contain the process-heartbeat stuff. It also has `group_vdbs.py` (→ `GroupVDBSTable` class for updating VDB status rows) and `group_llms.py` (→ `GroupLLMsTable` for LLM status). These are the "external dependency health" companions to the process heartbeat.

Plus helpers like:

- `get_outdated_status(row)` — decorates a status_text with `[Not updated]` or `[Outdated]` if the row's timestamp is too old (10 min). Used by the UI when rendering status cells.
- `is_need_to_check_llm(row)` — the 5-minute throttle for public LLM APIs

So the `common/watchdogs/` module actually encompasses **three distinct health-tracking concepts** that share infrastructure and philosophy:

1. **Process heartbeat** — am *I* (a specific worker) still alive? (`api_processes`, `WatchdogThread`)
2. **External-service health** — are the VDB servers and LLM endpoints my workers depend on reachable? (`group_vdbs`, `group_llms`, `VDBLLMStatusWorker`)
3. **Single-instance guard** — refuse to start if an identically-named process is already running (`check_name_is_still_running`)

All three bubble up to the admin dashboard.

---

## How it surfaces in the UI

Two pages in `cognosa_web_app/backend/cwa_lib/pages/`:

- `server_status.py` — what regular users see for their group: status of the VDB and LLM servers their group is configured to use.
- `su_server_status.py` — what superusers see: all of the above PLUS full `api_processes` readout showing every watchdog, polling loop, VDB subprocess, and status worker across every `run_tasks` instance. Stale rows (older than `AP_MAX_BEFORE`) are rendered as problems.

So the superuser page is effectively "one screen to see whether everything is alive: web server's task runners, their internal subprocesses, the external databases, the external LLMs."

---

## How this would port to p51_local_automator

Today p51 doesn't need any of this because:

- All work runs inside the single uvicorn process via FastAPI `BackgroundTasks`
- There are no external services to monitor (MCP subprocesses are spawned per call, not persistent)
- If uvicorn dies, everything dies — no "is the worker still alive" question to answer

But if p51 grows into these places, the cognosa pattern is directly reusable:

| p51 future scenario | Applicable pattern from cognosa |
|---|---|
| Heavy workflows moved to separate processes (avoid OOM / GIL contention) | Exactly this: `api_processes` + `WatchdogThread`, one `AP_NAME` per worker |
| Persistent MCP subprocesses (reuse Apple Mail / Calendar servers across calls) | Same watchdog wrapping the MCP supervisor process |
| External LLM/API health (e.g. is the Anthropic API up? Google OAuth token refresh service?) | Same as `VDBLLMStatusWorker` — periodic check, write to a status table, surface on admin page |
| Scheduler moved out-of-process | `APScheduler` instance with its own `AP_NAME = 'scheduler'` subname |
| "Is any workflow currently running?" admin question | A subset of the same data — count `workflow_runs` with `status='running'` |

The whole module is ~300 lines including tables. If we decide to build it into p51 later, copy the structure verbatim; the only project-specific bits are the DB model names (`api_processes` → whatever we call it) and the integration points (which workers spawn watchdogs).

For now p51's health model is "if uvicorn is up, everything's up" — which is correct for a single-process platform but will stop being sufficient as soon as out-of-process workers arrive.

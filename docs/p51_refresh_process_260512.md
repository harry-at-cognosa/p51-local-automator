# p51-local-automator — Refresh Process After `git pull`

**Last updated:** 2026-05-12
**Repo root:** `~/p51-local-automator` (resolves to your home dir on whichever machine)
**Venv:** `~/p51-local-automator/venv`

This is the checklist for getting the laptop back to a working state after
pulling new code. Most steps are conditional — only run them if the
relevant files changed. The "what changed" command at the top tells you
which sections you can skip.

---

## 0. Before you pull

Make sure your working tree is clean so the pull is a fast-forward, not a
merge.

```bash
cd ~/p51-local-automator
git status        # should show "working tree clean"
git pull          # if not clean: stash, pull, then stash pop
```

If `git status` is dirty:

```bash
git stash push -u -m "pre-pull stash"
git pull
git stash pop
```

---

## 1. See what actually changed

This tells you which of the steps below you can skip.

```bash
git diff --stat HEAD@{1} HEAD
```

Scan the output for these paths — each maps to a section below:

| Path that changed                       | Action needed                |
| --------------------------------------- | ---------------------------- |
| `backend/requirements.txt`              | §2 reinstall Python deps     |
| `backend/alembic/versions/*.py`         | §3 run migrations            |
| `frontend/.nvmrc`                       | §4a switch Node version (`nvm install && nvm use`) |
| `frontend/package.json` or `-lock.json` | §4b `npm install`             |
| `frontend/vite.config.ts`               | §4d restart Vite dev server (HMR does NOT reload proxy/server config) |
| `frontend/src/**`                       | §4c rebuild OR rely on Vite HMR; see section |
| `.env.example`                          | §5 reconcile your `.env`     |
| anything else (just `backend/**.py` etc.) | §6 just restart uvicorn    |

If nothing in the table matches, jump straight to §6 (restart).

---

## 2. Backend Python deps

Only if `backend/requirements.txt` changed.

```bash
cd ~/p51-local-automator
source venv/bin/activate
pip install -r backend/requirements.txt
```

> No "build" step exists for the backend — FastAPI is interpreted. The
> only artifact is whatever pip installs into the venv.

---

## 3. Database migrations

Run this if **either** of these is true:
- New files appeared under `backend/alembic/versions/`
- You just swapped in the database snapshot from the desktop

```bash
cd ~/p51-local-automator
source venv/bin/activate
alembic current        # what revision are we at?  [a8b3c5d7e9f2 (head) 26-05-12]
alembic heads          # what does the code expect?
alembic upgrade head   # bring DB up to code (idempotent)
```

`alembic upgrade head` is safe to run anytime — it's a no-op if already
at head.

**If a migration fails:** read the error, fix the underlying schema
issue (often a stale column or constraint from the swapped DB), then
re-run. Do **not** force-stamp without understanding the divergence.

---

## 4. Frontend

### Step 4a. Pin Node version (only if `frontend/.nvmrc` changed)

The repo pins Node via `.nvmrc`. If it changed (or you've never set up
nvm on this machine), bring your shell to the pinned version:

```bash
cd ~/p51-local-automator/frontend
nvm install      # reads .nvmrc, installs that Node version
nvm use          # switches the current shell to it
node --version   # should match .nvmrc
```

Re-run `npm install` after switching Node — node_modules built against
the old version may produce engine warnings or behave oddly.

### Step 4b. Refresh node_modules (only if `package.json` or `package-lock.json` changed)

```bash
cd ~/p51-local-automator/frontend
npm install
```

### Step 4c. Frontend source changes (`frontend/src/**`)

Two paths depending on how you access the app:

- **Vite dev server (`http://localhost:5173`)** — HMR handles it. No
  rebuild, no restart. Just save the file and the browser updates.
- **Backend-served bundle (`http://localhost:8000/app`)** — you need to
  rebuild:

  ```bash
  cd ~/p51-local-automator/frontend
  npm run build    # writes the bundle to backend/static/
  ```

  The backend serves whatever's in `backend/static/`, so the build must
  finish before reloading the page.

### Step 4d. Vite config changes (`frontend/vite.config.ts`)

HMR does **not** reload Vite's own server config (proxy entries, port,
plugins, etc.). If `vite.config.ts` changed, kill and restart the dev
server:

```bash
lsof -ti :5173 | xargs kill 2>/dev/null
cd ~/p51-local-automator/frontend
npm run dev
```

### Step 4e. Start the dev server (if not already running)

```bash
cd ~/p51-local-automator/frontend
npm run dev    # serves at http://localhost:5173 with hot reload
```

---

## 5. `.env` reconciliation

Only if `.env.example` changed (rare).

```bash
diff ~/p51-local-automator/.env.example ~/p51-local-automator/.env
```

For any key that exists in `.env.example` but not in your `.env`, add it
to your `.env` with your real value. Don't replace your `.env` wholesale
— it has live secrets (LLM API keys, `TOKEN_ENCRYPTION_KEY`,
`GOOGLE_CLIENT_*`, `DEFAULT_ADMIN_PASSWORD`, `DATABASE_URL`, etc.) that
the example file doesn't carry.

---

## 6. Restart the backend

```bash
# stop any running instance
lsof -ti :8000 | xargs kill 2>/dev/null

# start fresh
cd ~/p51-local-automator
source venv/bin/activate
python3 -m uvicorn backend.main:app --port 8000
```

For dev with auto-reload on file save, add `--reload`:

```bash
python3 -m uvicorn backend.main:app --reload --port 8000
```

---

## 7. Smoke test

```bash
# in another terminal
curl -fsS http://localhost:8000/docs >/dev/null && echo "docs OK"
curl -fsS http://localhost:8000/openapi.json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['info']['title'], d['info']['version'], '—', len(d['paths']), 'routes')"
```

**Expected output:**

```
docs OK
Local Automator API 0.1.0 — N routes
```

- `docs OK` means the FastAPI app is up and serving the Swagger UI.
- Title should be exactly `Local Automator API`. If it says something else, you hit the wrong server.
- Version `0.1.0` is the current value — it only changes when someone manually bumps it in `backend/main.py`, so don't worry if it stays at `0.1.0` for a long time.
- Route count grows as features land. As of 2026-05-12 PM (post D-track + T2S) it's **51 routes**; earlier that day it was 47; on 2026-05-02 it was 33. Don't expect a fixed number — just expect it to be ≥ what you saw last time (or close to it; routes occasionally get consolidated).

**Red flags:**
- `curl: (7) Failed to connect to localhost port 8000` → backend isn't running, or crashed during startup. Check `/tmp/p51-uvicorn.log` or wherever you redirected stdout.
- `docs OK` but the openapi line errors out → the app is partially up but something's broken in route registration. Look at the uvicorn log.
- Route count dramatically lower than last time → something failed to import on startup and routes silently didn't register. Check the log for `ImportError` / `ModuleNotFoundError`.

Then in a browser:
- http://localhost:8000/app (if you ran `npm run build`)
- http://localhost:5173 (if you ran `npm run dev`)

Login: `admin` / value of `DEFAULT_ADMIN_PASSWORD` in `.env` (usually `admin`).

---

## Quick-reference: "I just pulled, what now?"

The 90% case — code-only change, no deps, no migrations:

```bash
cd ~/p51-local-automator && git pull
# nothing else if requirements.txt / package.json / alembic/versions / .env.example are untouched
lsof -ti :8000 | xargs kill 2>/dev/null
source venv/bin/activate
python3 -m uvicorn backend.main:app --reload --port 8000
```

The full sweep when in doubt:

```bash
cd ~/p51-local-automator && git pull
source venv/bin/activate
pip install -r backend/requirements.txt
alembic upgrade head
( cd frontend && npm install && npm run build )
lsof -ti :8000 | xargs kill 2>/dev/null
python3 -m uvicorn backend.main:app --port 8000
```

Slow but safe — always works.

finding the servers when not in a terminal:

finding fastAPI vite and npm servers when no in a terminal window:

ps aux | grep -E "uvicorn|vite" | grep -v grep
or use 

A port-based alternative that's often easier:
  
  lsof -i :8000 -i :5173 -P -n
  Shows what's listening on those ports plus the PIDs.
  To stop them: kill <PID> from any of your shells works, since you own them.
    

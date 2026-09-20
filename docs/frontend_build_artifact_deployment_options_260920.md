# `backend/static/` — what it is, and three ways to deploy it

**Status:** open question, no decision made. Captured 2026-09-20 so the
trade-off isn't re-derived from scratch later.

## What `backend/static/` actually is

It is **build output on the server**, not source, and not anything that lives on
a browser.

`frontend/vite.config.ts` sets:

```ts
build: {
  outDir: "../backend/static",
}
```

So `npm run build` compiles `frontend/src/**` into hashed bundles and writes them
into `backend/static/`. `backend/main.py` then mounts that directory:

```python
app.mount("/app/assets", StaticFiles(directory=_assets_dir), name="static-assets")
```

and serves `backend/static/index.html` at `/app/`.

```
Mac Mini (server)                               browser (client)
─────────────────                               ────────────────
frontend/src/*.tsx
      │  npm run build   (requires node + npm install)
      ▼
backend/static/assets/index-<hash>.js  ──HTTP──►  runs the JS
      ▲                                            (builds nothing)
      └── StaticFiles mount at /app/assets
```

The browser is the client. It downloads the bundle and executes it; it never
compiles anything. The build happens on whichever machine runs `npm run build`,
which today is the same Mac Mini that serves the app — there is no CI and no
separate build host.

## Why it's gitignored

`.gitignore` line 11 (`backend/static/`), sitting in the same block as
`node_modules/`, `dist/`, and `frontend/dist/`. It has been there since the
first commit of the web app — `c855dbd`, 2026-04-15, "Phase 2: Foundation web
app" — and the directory has **never** been tracked in any branch.

This was not a considered decision about this project; it is the default
convention that arrived with the scaffold. The usual justifications do apply:

- Minified bundles produce enormous, unreadable diffs on every build.
- Content-hashed filenames change each build, so stale files accumulate unless
  something prunes them.
- Two machines building the same source can emit byte-different output, which
  turns routine pulls into merge conflicts over generated files.

## Why it matters here

p51 is deployed by `git pull` onto a Mac Mini. There is no build pipeline
between the repo and the running service. Because the artifact is ignored, the
repo does not contain a usable UI — only the source for one.

The practical failure mode is documented in
`docs/p51_refresh_process_after_git_pull_260512.md` §4c and is easy to hit:

> Pull the code, restart uvicorn, and `:8000/app` still serves the **old**
> bundle — silently — because nobody ran `npm run build`.

The backend reports the new version and the UI does not reflect it. Nothing
errors. `/api/v1/system/version` will show the new `app_version` and `git_sha`
while the browser is still running last week's JavaScript.

This also sets a floor on what a deployment target needs: node, npm, and a
successful `npm install` of the full dependency tree, purely to render a page —
on an appliance that otherwise needs only Python, PostgreSQL, and node-for-MCP.

## Three options

### 1. Build on each site (current behavior)

Keep `backend/static/` ignored; `npm run build` is a mandatory deploy step
wherever the app runs.

- **Pros:** clean repo, no generated files in history, no conflicts, zero
  process change.
- **Cons:** every deployment target needs a JS toolchain; "pull and restart" is
  not sufficient and the failure is silent; `npm install` at a customer site is
  a network- and time-dependent step that can fail on its own.
- **Fits:** a single box operated by the person who wrote the code.

### 2. Commit the bundle

Un-ignore `backend/static/` and commit build output alongside source.

- **Pros:** `git pull` + restart is genuinely sufficient; target machines need
  no node for the frontend at all; impossible to run a stale UI against fresh
  backend code.
- **Cons:** noisy diffs on every build; hashed files accumulate unless pruned;
  requires discipline that builds happen on one designated machine, or pulls
  will conflict over generated files.
- **Fits:** an appliance deployed by pulling, where operational simplicity at
  the target outweighs repo cleanliness.

### 3. Ship a release artifact

Build once on a designated machine, attach a tarball of `backend/static/` to a
GitHub release (or any artifact store), unpack it on the target.

- **Pros:** repo stays clean *and* customer boxes need no JS toolchain;
  the deployed UI is a versioned, identifiable thing rather than whatever the
  local build happened to produce; naturally pairs the bundle with the CalVer
  version it was built from.
- **Cons:** adds a release step that must not be forgotten; needs a documented
  unpack procedure and a way to verify bundle/backend version agreement.
- **Fits:** the multi-customer model in
  `docs/p51_deployment_modes_macmini_260525.md`.

## Leaning

For the current single personal box, option 1 is fine and nothing needs to
change. If and when p51 ships to a customer Mac Mini, option 3 is the one to
reach for — it keeps the customer machine free of a JavaScript toolchain
without putting minified output into git history.

Whichever way this goes, the silent-stale-bundle failure in §4c of the refresh
runbook deserves a guard: a startup check comparing the built bundle's version
against `backend.__version__`, logged like the existing
`alembic_revision_mismatch` warning.

## Related

- `docs/p51_refresh_process_after_git_pull_260512.md` — §4c, the build step
- `docs/mac_mini_deployment.md` — unattended deployment on this box
- `docs/p51_deployment_modes_macmini_260525.md` — single-user vs. team modes

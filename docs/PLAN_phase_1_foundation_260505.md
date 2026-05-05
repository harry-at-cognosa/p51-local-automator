# Phase 1 Implementation Plan — file_system_root, config_snapshot, seed gating

**Date planned:** 2026-05-05
**Status:** Planned, not yet executed.

## Order of operations

The three Phase 1 items are sequenced as: config_snapshot first (purely additive), then file_system_root (adds a runtime check + needs data migration for existing groups), then seed gating (last, so the new state has alembic-driven defaults already in place).

Reversibility:
- Commits 1, 2, 5, 6 are reversible (code-only or downgradable migration).
- Commit 3 (data migration writing api_settings/group_settings rows) is technically reversible but in practice "no going back" once a deployment has run real workflows under the new path.
- Commit 4 (engine wiring to require root) is the hard cut-over.

---

## Commit 1 — Schema migration for `workflow_runs.config_snapshot`

**Alembic migration** at `backend/alembic/versions/<new>_workflow_runs_config_snapshot.py`:

- `upgrade`: `op.add_column("workflow_runs", sa.Column("config_snapshot", sa.JSON(), nullable=True))`. Leave NULL for historical rows. No backfill (we don't have the original config; pretending to is worse than NULL).
- `downgrade`: `op.drop_column("workflow_runs", "config_snapshot")`.

**Model edit** at `backend/db/models.py` (`WorkflowRuns`): add `config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)`.

**Verification**: alembic upgrade head; `\d workflow_runs` shows the new column; existing run rows still readable; existing `WorkflowRunRead` Pydantic schema still serializes them (column is optional).

Reversible commit — no behavioral change yet.

## Commit 2 — Engine writes `config_snapshot` at run start

**Code edit** at `backend/services/workflow_engine.py`:

- `create_run` gains a `config: dict | None = None` parameter and writes it to `WorkflowRuns.config_snapshot`.
- All six callers in `backend/services/workflows/*.py` pass `workflow.config` through. The workflow object is already in scope at every call site.
- Pydantic schema at `backend/db/schemas.py:WorkflowRunRead` gains `config_snapshot: dict | None = None`.

**Verification**: trigger a manual run of any existing workflow via the UI's Run button; `select run_id, config_snapshot from workflow_runs order by run_id desc limit 1;` returns the workflow's current config. Edit the workflow's config, run again, confirm the second run captured the new config and the first row's snapshot is unchanged. NULL rows from before this commit remain NULL.

Reversible.

---

## Commit 3 — Data migration for `file_system_root`

**Alembic migration** at `backend/alembic/versions/<new>_seed_file_system_root.py`:

- `upgrade`: insert `api_settings('file_system_root', '/Users/harry/p51_output_area')` if absent (single-user Mac default; the deployed Mac Mini overrides per-group). **No per-group rows seeded** — the absence of a per-group row is the signal "fall through to global." This matches the resolution chain (group → api → error) cleanly without giving every group an identical override row to maintain.
- `downgrade`: delete the api_settings row only; do not touch group_settings rows in case operators set them manually.

**Bootstrapping decision**: set the global `api_settings.file_system_root` only. Don't seed per-group overrides for the existing System and Default Group. Reason: per-group rows mean "this group has a different root than the platform default." Seeding them at install with the platform default value makes that distinction meaningless and obscures intent. On the Mac Mini deployment, the operator overrides the global value (or sets per-group rows for genuinely different roots). On the desktop deployment, the global default just works.

**Verification**: `select * from api_settings where name='file_system_root';` returns the seeded row. `select * from group_settings where name='file_system_root';` returns nothing. Run any existing workflow — still works (this commit didn't change the engine yet).

## Commit 4 — Engine reads `file_system_root` and resolves the chain

**Code edits**:

- `backend/services/workflow_engine.py`: rewrite `get_run_output_dir`. Make it `async` and pass it the `AsyncSession`. New behavior:
  1. `select group_settings.value where group_id=:g and name='file_system_root'` — if found, use it.
  2. Else `select api_settings.value where name='file_system_root'` — if found, use it.
  3. Else raise `RuntimeError("file_system_root is not configured for group {group_id}; set group_settings or api_settings 'file_system_root'")`.
  4. Path becomes `<root>/{group_id}/{user_id}/{workflow_id}/{run_id}/`. Keep `os.makedirs(path, exist_ok=True)`.
- All six call sites in `backend/services/workflows/*.py` become `await engine.get_run_output_dir(session, workflow.group_id, ...)`. Session is already in scope at each call site.
- Add a sibling helper `get_workflow_inputs_dir(session, group_id, user_id, workflow_id)` that resolves the same root and returns `<root>/{group_id}/{user_id}/{workflow_id}/inputs/`. Don't wire it into type 2 yet (leave `data_analyzer.py:config.file_path` permissive). The helper exists for the file-picker work later.
- Remove the project-rooted `data/` reference. Don't delete the directory itself — out of scope.

**Verification**:
- With api_settings row in place, run a workflow — output appears under `/Users/harry/p51_output_area/{group_id}/{user_id}/{workflow_id}/{run_id}/`.
- Insert a `group_settings` override (`group_id=2`, `name='file_system_root'`, `value='/tmp/p51_alt'`); run a workflow owned by group 2 — output goes to `/tmp/p51_alt/2/...`.
- Delete both rows in a test DB; trigger a run; confirm the run fails with the configuration error and `workflow_runs.status='failed'` with a clear `error_detail`.

This is the cut-over commit. Type 2's existing absolute `file_path` continues to work because `data_analyzer.py`'s validator is unchanged.

---

## Commit 5 — Gate `run_seed`

**Sentinel choice**: `workflow_types` non-empty.

Reasoning vs `api_settings.app_title`:
- Most direct signal for what seed primarily does going forward (categories + types). `app_title` could exist for unrelated reasons.
- Resilient to operators tweaking app_title from the UI: even if someone clears it, we don't accidentally re-seed and overwrite curated workflow_type rows.
- A genuinely empty fresh DB has no workflow_types, so the developer-from-scratch path still triggers the full seed.

**Code edit** at `backend/db/seed.py`: at the top of `run_seed`, open a session and `select count() from workflow_types`. If `> 0`, log `[seed] workflow_types already populated; skipping seed.` and return. Otherwise proceed with the existing flow.

Leave the seed file in place — keeps it discoverable and the existing `run_seed_sync` entrypoint still works for `python -m backend.db.seed` style bootstrap.

**Verification**:
- Existing populated DB: restart backend; logs show the skip message; no DB writes from seed.
- Drop `workflow_types` rows in a scratch DB; restart; full seed runs and re-populates.
- `app.py` lifespan untouched — `run_seed()` still called, just becomes a no-op on populated DBs.

## Commit 6 (optional) — docs + BACKLOG

Update `docs/BACKLOG.md`: mark these items done; add a note that future workflow_type/category changes go through Alembic data migrations, not seed edits. Add a note that `config_snapshot` UI surfacing is deferred.

---

## Risks and mitigations

**Run after item 1 lands but no `file_system_root` configured.** Engine raises and the run row records `status='failed'`, `error_detail='file_system_root is not configured...'`. Mitigation: commit 3's data migration seeds the global default before commit 4's engine change, so on every deployment moving through these commits in order the chain is non-empty by the time the engine starts requiring it. A fresh dev install gets the global default via the same migration.

**Old `workflow_runs` rows have NULL `config_snapshot`.** Expected and intended. The Pydantic schema declares it `dict | None`, so the API returns `null`. UI surfacing is out of scope — when it lands later, render NULL as "config not captured (pre-Phase 1 run)." Don't backfill.

**Concurrency / restart.** Single backend instance assumption holds. `os.makedirs(exist_ok=True)` is safe under concurrent runs. The new resolution query happens once per run at run-start (cheap, indexed by PK on group_settings, by PK on api_settings). No caching needed — adds restart-stale-cache risk for the value of `file_system_root` if an operator changes it at runtime; better to read fresh.

**SMB mount disappearing mid-run.** Out of scope (mount management is a deployment concern). Engine surfaces IOError and fails the run — same as a local disk full.

**Seed gating regression on a half-migrated DB.** Sentinel is `workflow_types` non-empty, independent of api_settings, so this isn't a coupling problem. But deploy order across commits 3 → 4 → 5 still matters for the file_system_root chain.

---

## Commit boundaries summary

Six commits, each independently shippable and verifiable:

1. Migration: add `workflow_runs.config_snapshot` column + model field. Ship.
2. Engine writes `config_snapshot`; schema exposes it. Ship and verify a new run captures config.
3. Migration: insert `api_settings.file_system_root` global default. Ship and verify row exists.
4. Engine resolves root via chain; all callers updated. **Cut-over.** Ship and verify outputs land at the new path.
5. Seed gates on `workflow_types` non-empty. Ship and verify restart logs the skip.
6. (optional) Docs/BACKLOG cleanup.

Frontend untouched — engine changes are server-side; the run-list UI keeps working because `WorkflowRunRead` only gained an optional field.

## Critical files for implementation

- `backend/services/workflow_engine.py`
- `backend/db/models.py`
- `backend/db/seed.py`
- `backend/db/schemas.py`
- `backend/alembic/versions/` (two new migration files)

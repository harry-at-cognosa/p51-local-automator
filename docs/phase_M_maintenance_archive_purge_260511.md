# Phase M — Maintenance: archive + purge

Two-tier housekeeping for accumulated run data. Decided 2026-05-11 after Harry noted that soft-deleted workflows leave runs, steps, artifacts, and on-disk files in place indefinitely. Today the orphan footprint is small (1 of 64 soft-deleted workflows has any run data); the policy is being built before it becomes an actual problem.

## Goals

1. Archive — reversibly hide old run data from all users. DB rows + on-disk files stay where they are; a single column tags them. Recoverable by flipping the bit.
2. Purge — irreversibly delete old run data from the DB and the file system. No undo.
3. Both operations are superuser-only, runnable from a new admin page, against a single group or all groups, with a date cutoff.
4. Dry-run preview before any commit. Mandatory confirmation gate for purge.
5. Audit row written per non-dry-run action.

## Decisions locked

- Granularity: per-run. Each `workflow_runs` row is independently archivable/purgeable. A workflow with 30 old runs and 2 new ones keeps its newest 2 visible.
- On-disk handling for archive: tag-only. Files stay in place. No move-to-archive folder.
- On-disk handling for purge: hard-delete the run's subdirectory (`<file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/`). The workflow-level and user-level inputs sandboxes are untouched.
- Soft-deleted workflows: archive sweep auto-includes them regardless of date. Purge sweep drops the workflow row itself once it has zero remaining runs AND `deleted=1`.
- Workflows that have never run: skipped by archive. Picked up by purge only if soft-deleted.
- Audit log lives in a new `maintenance_log` table; admin page reads it for a history view.
- Date interpretation: cutoff is `started_at < cutoff` (inclusive of the start of the cutoff day, exclusive of anything from that day forward).

## Schema changes

### `workflow_runs.archived: boolean NOT NULL DEFAULT FALSE`

One new column on the existing table. Indexed-partial on `archived = true` is unnecessary — sweep queries filter on date + group, not archived state.

All read queries that currently show runs to non-superusers must add `archived = false` to their `where`. Affected query sites identified during M.2.

### `maintenance_log` table

```sql
CREATE TABLE maintenance_log (
    log_id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    operation           VARCHAR(16) NOT NULL,  -- 'archive' | 'purge'
    user_id             INTEGER NOT NULL REFERENCES api_users(user_id),
    scope               VARCHAR(16) NOT NULL,  -- 'all' | 'group'
    scope_group_id      INTEGER REFERENCES api_groups(group_id),  -- NULL when scope='all'
    cutoff              TIMESTAMPTZ NOT NULL,
    workflows_affected  INTEGER NOT NULL DEFAULT 0,
    runs_affected       INTEGER NOT NULL DEFAULT 0,
    steps_affected      INTEGER NOT NULL DEFAULT 0,
    artifacts_affected  INTEGER NOT NULL DEFAULT 0,
    bytes_freed         BIGINT,                -- NULL for archive (no rm); set for purge
    error_detail        TEXT,                  -- NULL on success; first ~1000 chars on failure
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_maintenance_log_created_at ON maintenance_log (created_at DESC);
```

Only non-dry-run commits write a row. Dry-runs return counts without persisting anything.

## Backend endpoints

All routes under `/admin/maintenance/`, all gated on `current_active_user.is_superuser`. Non-superusers get 403.

### `POST /admin/maintenance/archive`

```jsonc
{
  "scope": "all" | "group",
  "group_id": 2,             // required when scope="group"
  "cutoff": "2026-01-01",    // YYYY-MM-DD
  "dry_run": true            // if false, commit
}
```

Action (commit path):

1. Resolve the set of `run_id`s where `started_at < cutoff AND archived = false`, filtered by group if `scope=group`.
2. Union with all `run_id`s from workflows where `deleted = 1 AND archived = false` (soft-deleted-include rule, no date filter).
3. `UPDATE workflow_runs SET archived = TRUE WHERE run_id = ANY(:ids)` — single statement.
4. Count distinct workflow_ids touched, total steps/artifacts attached, write `maintenance_log` row.

Response (both dry-run and commit):

```json
{
  "workflows_affected": 12,
  "runs_affected": 47,
  "steps_affected": 312,
  "artifacts_affected": 89,
  "soft_deleted_workflows_included": 6
}
```

### `POST /admin/maintenance/purge`

```jsonc
{
  "scope": "all" | "group",
  "group_id": 2,
  "cutoff": "2026-01-01",
  "dry_run": true,
  "confirmation": "PURGE"     // required when dry_run=false; rejected with 400 otherwise
}
```

Action (commit path):

1. Resolve `run_id`s the same way archive does.
2. For each run, in order:
   - Compute on-disk byte total (recursive sum) before deletion.
   - `DELETE FROM workflow_artifacts WHERE run_id = :r`.
   - `DELETE FROM workflow_steps     WHERE run_id = :r`.
   - `DELETE FROM email_auto_reply_log    WHERE pending_id IN (SELECT pending_id FROM pending_email_replies WHERE run_id = :r)`. Sets up the next delete.
   - `DELETE FROM pending_email_replies WHERE run_id = :r`.
   - `DELETE FROM workflow_runs WHERE run_id = :r`.
   - `rm -rf <file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/` (resolved via group_id lookup chain).
3. After all targeted runs purged, find soft-deleted workflows with zero remaining runs and drop them: `DELETE FROM user_workflows WHERE deleted = 1 AND workflow_id NOT IN (SELECT DISTINCT workflow_id FROM workflow_runs)`.
4. Write `maintenance_log` row with byte total.

Response (both):

```json
{
  "workflows_affected": 12,
  "workflows_dropped": 6,     // soft-deleted that lost their last run
  "runs_affected": 47,
  "steps_affected": 312,
  "artifacts_affected": 89,
  "bytes_freed": 412300000
}
```

Failure handling: any step that errors aborts the rest of THAT run's purge, logs `error_detail` on the maintenance_log row, and continues to the next run. The transaction is per-run, not per-sweep — partial completion is OK and recorded.

### `GET /admin/maintenance/log?limit=50`

Returns recent `maintenance_log` rows for the history view.

### `GET /admin/maintenance/preview` (optional convenience)

Same shape as the POST endpoints with `dry_run=true`. Aliased for clarity — could just use the POST endpoints with the flag set.

## Visibility / read-side changes (M.2)

Add `AND workflow_runs.archived = false` (or join + filter) to every query that surfaces runs to non-superuser views:

- `backend/api/workflows.py:list_workflows` — latest-run subquery should pick the latest *non-archived* run.
- `backend/api/workflows.py:list_runs` — runs table on WorkflowDetail.
- `backend/api/workflows.py:get_run` and the runs response models.
- `backend/api/artifacts.py` — artifact download should 404 if the parent run is archived AND the requester isn't superuser.

Superuser-only override: a `?include_archived=true` query string on the list and runs endpoints, gated on `user.is_superuser`. Ignored (silently false) for non-superusers.

## Frontend admin page (M.6)

Path: `/app/admin/maintenance`. Sidebar link added under "Admin" after the existing workflow-categories and workflow-types links. Hidden for non-superusers (same gating the other admin pages use).

Layout:

```
┌────────────────────────────────────────────────────────────┐
│ Maintenance                                                │
│                                                            │
│ Operation:    ( ) Archive   ( ) Purge                      │
│ Scope:        ( ) All groups   ( ) One group [dropdown]    │
│ Cutoff:       [date picker — default: 1 year ago]          │
│                                                            │
│ [ Preview ]                                                │
│                                                            │
│ ┌─ Preview results ─────────────────────────────────┐     │
│ │ Would archive 47 runs across 12 workflows         │     │
│ │ (6 of them soft-deleted, all runs auto-archived)  │     │
│ │ Steps: 312    Artifacts: 89                       │     │
│ └───────────────────────────────────────────────────┘     │
│                                                            │
│ For purge only:                                            │
│  Type PURGE to confirm: [_______]                          │
│  [ Commit Purge ]   (disabled until confirmation matches)  │
│                                                            │
│ For archive:                                               │
│  [ Commit Archive ]                                        │
│                                                            │
│ ── Maintenance history ────────────────────────────────    │
│  date          op       user     scope  cutoff       cnt  │
│  2026-05-11    archive  admin    all    2026-01-01    47  │
│  2026-05-11    purge    admin    grp 2  2025-12-01    12  │
└────────────────────────────────────────────────────────────┘
```

Behaviors:

- Preview button always available; fires the dry-run endpoint, shows the result panel.
- Result panel must be visible before either Commit button is enabled. (Forces a look-before-leap.)
- Changing any input (operation, scope, cutoff) invalidates the preview — buttons disable again until re-previewed.
- Purge commit requires typing the exact literal `PURGE` in the confirmation field. Frontend does the check before enabling the button; backend re-validates.
- After a successful commit, the history table refreshes from the log endpoint.
- Failure toast on non-2xx response, history table still refreshes (a failed sweep wrote a log row with `error_detail`).

## Superuser show-archived toggle (M.7)

On WorkflowDetail's runs table: a small "Show archived" switch in the table header. Visible only when `user.is_superuser`. Default off. When on, refetches with `?include_archived=true`. Archived rows are visually distinguished (italicized, faded, or a small "archived" badge — choice TBD during M.7).

Same toggle could appear on the Workflows list page later for completeness, but not in this phase — workflow-level hiding is unchanged; only run-level hiding is the M change.

## Commit plan

- M.1 — Alembic migration: `workflow_runs.archived` column + `maintenance_log` table.
- M.2 — Backend read-side filter changes. All run-surfacing queries get `archived=false`. Optional `?include_archived=true` flag gated on `is_superuser`. No new endpoints yet.
- M.3 — Backend: `POST /admin/maintenance/archive` (dry-run + commit, single endpoint, branched on `dry_run`).
- M.4 — Backend: `POST /admin/maintenance/purge` (dry-run + commit, with confirmation gate). Includes on-disk `rm -rf` logic and the soft-deleted-workflow-cleanup step.
- M.5 — Backend: `GET /admin/maintenance/log`. Tiny.
- M.6 — Frontend: `/app/admin/maintenance` page with preview/commit/history UI.
- M.7 — Frontend: superuser "show archived" toggle on WorkflowDetail's runs table.
- M.8 — Frontend: sidebar admin link.
- M.9 — Docs: BACKLOG mark, CLAUDE.md notes (one sentence on new admin page + audit table), small smoke-test runbook captured here when shipping.

## Smoke-test runbook (filled in at M.9)

To be run after each commit at minimum; full sweep before marking M shipped:

1. Log in as admin. Navigate to `/app/admin/maintenance`. Page renders, history empty.
2. Pick Archive / All groups / cutoff = today. Preview shows nonzero counts (most runs are eligible). Commit. Verify Workflows page now shows fewer "Last run" entries (latest-run subquery now sees fewer rows).
3. WorkflowDetail page for a workflow with archived runs: runs table is shorter. Flip the superuser "show archived" switch — full list returns.
4. Log in as a non-superuser (cogmgr). `/app/admin/maintenance` is hidden from sidebar; direct nav 403s. WorkflowDetail's runs table has no toggle; archived runs are hidden.
5. Back as admin. Archive a soft-deleted workflow's runs implicitly: soft-delete one of admin's workflows, run Archive again — counts increase by that workflow's runs.
6. Purge dry-run: pick Purge / All groups / cutoff = yesterday. Confirm Preview shows reasonable numbers. Type `purge` (lowercase) in confirmation — button stays disabled. Type `PURGE` — button enables.
7. Purge commit. Verify `workflow_runs` row count drops, `workflow_steps` and `workflow_artifacts` and `pending_email_replies` and `email_auto_reply_log` drop transitively, on-disk run directories under `<file_system_root>/.../{run_id}/` are gone, and any soft-deleted workflow with zero remaining runs has its `user_workflows` row dropped.
8. `SELECT * FROM maintenance_log ORDER BY created_at DESC LIMIT 5;` — last actions visible with correct user_id, scope, counts, bytes_freed.

## What this phase deliberately does not change

- The soft-delete behavior of the workflow delete button. Users still soft-delete; archive/purge is admin-driven on top.
- The workflow-creation or workflow-edit flows.
- The on-disk inputs sandbox (`<file_system_root>/{group_id}/{user_id}/inputs/`). Purge only touches run subdirectories.
- The `gmail_accounts`, `gmail_token_usage` tables. These are per-user state, not per-run.
- File-picker output, run-detail page rendering. They keep working; only the row visibility filters change.

## Reversibility

- Archive: fully reversible. `UPDATE workflow_runs SET archived = false WHERE …` undoes everything. Worth providing a "Unarchive" button on the maintenance history row that reverses one past action, but defer to a follow-up if not in M.6's first cut.
- Purge: not reversible. Rows are gone, files are rm'd. Mitigations:
  - Mandatory dry-run preview before commit.
  - Mandatory `PURGE` confirmation literal.
  - Audit log row tells you exactly what was purged after the fact (counts, not contents).
  - Recommend a DB snapshot before any large-scope purge; document in the runbook.

## Estimated effort

- M.1 — 20 min (schema + migration).
- M.2 — 40 min (read-side filters across multiple endpoints + tests).
- M.3 — 30 min (archive endpoint).
- M.4 — 60 min (purge endpoint; the on-disk rm is the tricky bit).
- M.5 — 10 min.
- M.6 — 60-90 min (admin page with all states).
- M.7 — 20 min (toggle + styling).
- M.8 — 5 min.
- M.9 — 20 min (BACKLOG, CLAUDE.md, runbook execution).

Roughly 5 hours of focused work. Sized for a single sitting if there are no interruptions.

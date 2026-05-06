# P51 Local Automator — Backlog

Running list of decisions, enhancements, and ideas captured during architecture discussions. Each item links to its detailed note where one exists.

## New workflow types to implement

- **Interactive single-file analyzer** (human-only, not schedulable) — at run time, the user picks a file via a picker scoped to their sandbox; the workflow runs against that file. Same analysis pipeline as type 2; the difference is "config provides no path, run-time UI does." Cannot be triggered by cron.
- **Folder-batch analyzer** — config holds a folder path under the user's sandbox. At run time, the workflow processes every eligible file in that folder, one at a time. Needs a "processed/" subdirectory or a small ledger so scheduled runs don't re-process the same files.

## UI / UX

- ~~[Workflow Detail page header](enhancement_workflow_detail_header_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.1`).
- ~~[Workflow Detail layout](enhancement_workflow_detail_stack_layout_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.1`).
- ~~Hint copy on workflow create form~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.2`).
- ~~File-picker UI for any path-config field, restricted to `<file_system_root>/{group_id}/{user_id}/inputs/`~~ — **shipped 2026-05-06** in Phase F1 (commits `phase F1.1` through `phase F1.6`). New `file_picker` and `repeating_rows` field types in `SchemaConfigForm`, plus `<FilePicker>` modal and `GET /api/v1/files/list` endpoint. AWF-1 will consume both via its config_schema in A1.
- ~~**Workflow list sort options**~~ — **shipped 2026-05-06** in commit `d39cf5e`. Sort selector above the VCR pager offers three descending sorts: `workflow_id` (default), `last_run_at` (NULLs to bottom), `created_at`. Choice is persisted via the same Zustand persist as page size.

## Storage and deployment

- ~~[Per-group file_system_root](enhancement_file_system_root_per_group_260505.md)~~ — **shipped 2026-05-05** in Phase 1 (commits `phase 1.3`, `phase 1.4`). Resolution chain: group_settings → api_settings → error.
- **Standardize SMB mount point name across all clients** — when moving the backend to the Mac Mini, ensure desktops mount the share at the same POSIX path the backend uses (e.g., `/Volumes/p51_user_data`). Document the mount step in deployment instructions. Defer until the Mac Mini deployment work begins.

## Artifacts

- ~~[Downloaded filename includes run metadata](enhancement_artifact_download_filename_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.3`).

## Architecture / data model decisions still open

- ~~**Run config snapshot**~~ — **shipped 2026-05-05** in Phase 1 (commits `phase 1.1`, `phase 1.2`). `workflow_runs.config_snapshot` JSON column captures the user_workflows.config in effect at run start. UI surfacing of the snapshot is deferred (see below).
- ~~**Surface config_snapshot in the UI**~~ — **shipped 2026-05-06** in Phase F3 (commits `phase F3.1`, `phase F3.2`). Generic `<ConfigSnapshotPanel>` renders the snapshot against the workflow type's `config_schema` for any type that has one; falls back to raw JSON otherwise; shows "config not captured (older run)" for pre-Phase-1 NULL rows. Phase 1.2 had wired the engine-side capture but never wired `run.config_snapshot` through the API response — F3.1 fixed that gap.
- **Workflow type dispatch** — currently a 6-branch `if type_id == N` switch on integer PKs. Replace with a registry keyed on a stable type identifier (e.g., a renamed `type_name` that becomes `type_key`).
- ~~**Schema-driven workflow config form** (groundwork)~~ — **shipped 2026-05-05** in Phase 5 (commits `phase 5.1` through `phase 5.3`). Added `workflow_types.config_schema` JSON column populated for the six existing types. New `SchemaConfigForm` renders the form from a schema. `WorkflowConfigForm` keeps the typeId switch as the primary path; falls through to `SchemaConfigForm` when no typeId branch matches. Future types can ship a schema and skip writing a hand-tuned branch.
- **Migrate existing types from typeId switch to schema-driven** — followup to the groundwork above. Types 1–6 each have a `config_schema` populated in the DB; their hand-tuned typeId branches in `WorkflowConfigForm.tsx` could be removed once the generic renderer is verified to match the existing UX. Defer until a real reason to do it.
- **TS / Python type sharing** — frontend types are hand-written per page. Generate from FastAPI OpenAPI schema, or accept manual sync.
- **Conversations tables** (conversations, conversation_messages) — defined but unused. Keep for future chat layer or drop.
- ~~**Stop calling seed.py on startup**~~ — **shipped 2026-05-05** in Phase 1 (commit `phase 1.5`). `run_seed` now skips when workflow_types is non-empty. Future workflow_type/category changes go through Alembic data migrations rather than seed edits.

## Admin

- ~~**CRUD pages for workflow_categories and workflow_types**~~ — **shipped 2026-05-05** in Phase 3 (commits `phase 3.1`, `phase 3.2`, `phase 3.3`). Superuser-only pages at `/app/admin/workflow-categories` and `/app/admin/workflow-types`. No Add (new rows ship via Alembic migrations). No Delete (use the enabled toggle).

## Smaller fixes / cleanups

- `scheduler_service.py` parses `days_of_week` from schedule JSON but never enforces it.
- `SECRET=change-me-in-production` and `DEFAULT_ADMIN_PASSWORD=admin` defaults need a deployment-readiness check.
- `mcp/` directory is empty despite CLAUDE.md saying start scripts live there.
- Soft-deleted groups still own files under their `data/` subtree — decide whether to archive or delete.
- **Expose hard limits as config fields** — several runners have hardcoded fetch caps that should be per-workflow config with sensible defaults. Captured 2026-05-06.
  - `email_monitor.py:141,145` — `limit=100` for both apple_mail and gmail paths. Add `config.max_emails` (default 100, max maybe 500).
  - `calendar_digest.py` — `config.days` already exposed (default 7), but no per-event cap. Probably fine for v1; revisit if a long horizon explodes the LLM context.
  - `email_auto_reply_engine.py:339` — `fetch_limit` is already exposed in types 5/6 config (default 50). Harmonize naming with the new email_monitor field once added.
  - Frontend: surface the new fields in the typeId branches of `WorkflowConfigForm.tsx` and in the type 1 / type 3 `config_schema` migrations.
- ~~**Per-workflow run lock**~~ — **shipped 2026-05-06** in Phase F5 (commits `phase F5.1` through `phase F5.5`). Postgres partial unique index on `workflow_runs(workflow_id) WHERE status IN ('pending','running')` enforces "one active run per workflow" at the DB. `trigger_run` and `_run_workflow_background` both pre-check and return 409 / log structured skip. Startup watchdog flips abandoned ('running' for >24h) rows to 'failed'. Frontend Run Now button surfaces the 409 message inline. Closes the auto-reply double-process race for types 5/6 as a side effect; mandatory for AWF-1 given run cost/duration.

## Track B (Gmail / Workspace)

- ~~**B1 — Read-only Gmail for Type 1**~~ — **shipped 2026-05-06** in commits `phase B1.1` through `phase B1.10`. Per-customer GCP project model. New tables `gmail_accounts` + `gmail_token_usage`; AES-GCM encryption helper at `backend/services/secrets.py` (TOKEN_ENCRYPTION_KEY env var). OAuth flow at `/api/v1/gmail/oauth/{start,callback}` with state JWT signed by SECRET. Read-only `gmail_client.py` mirrors mcp_client.mail_* shape. `email_monitor.py` branches on `config.service`: apple_mail (existing) or gmail (new account_id-driven). Frontend Connections page + side menu link. Type 1 form gains service+gmail-account picker. Backend boots clean without `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` set; OAuth start returns 503 until configured.
- **B2 — Gmail send/draft for types 5 & 6** — depends on B1 + type 4 secrets reuse. Adds `gmail.send` and `gmail.compose` scopes; existing OAuth flow upgrades scope on re-consent. Send/save-draft logic in `email_auto_reply_*.py` branches on `service`. Pending-reply approval queue dispatch becomes service-aware.
- **B3 — Domain-wide delegation** (deferred). Per Track B scoping doc; revisit when a Workspace customer asks.
- **B4 — Consumer @gmail.com support** (deferred indefinitely).
- **Type 4 connection_string encryption** — small follow-on phase. Reuse `backend/services/secrets.py` to wrap the plaintext `connection_string` in user_workflows.config for type 4 (SQL Query Runner). Migrate existing rows opportunistically on next workflow edit.

## Notes

- [User story for workflow categories, types, and user workflows](user_story_workflow_categories_types_and_user_workflows.md) — captures the user-facing model: catalog is fixed, users clone-and-name, multiple instances per type, tune in place, retire by disable.

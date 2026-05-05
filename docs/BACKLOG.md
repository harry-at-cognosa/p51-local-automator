# P51 Local Automator — Backlog

Running list of decisions, enhancements, and ideas captured during architecture discussions. Each item links to its detailed note where one exists.

## New workflow types to implement

- **Interactive single-file analyzer** (human-only, not schedulable) — at run time, the user picks a file via a picker scoped to their sandbox; the workflow runs against that file. Same analysis pipeline as type 2; the difference is "config provides no path, run-time UI does." Cannot be triggered by cron.
- **Folder-batch analyzer** — config holds a folder path under the user's sandbox. At run time, the workflow processes every eligible file in that folder, one at a time. Needs a "processed/" subdirectory or a small ledger so scheduled runs don't re-process the same files.

## UI / UX

- ~~[Workflow Detail page header](enhancement_workflow_detail_header_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.1`).
- ~~[Workflow Detail layout](enhancement_workflow_detail_stack_layout_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.1`).
- ~~Hint copy on workflow create form~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.2`).
- File-picker UI for any path-config field, restricted to `<file_system_root>/{group_id}/{user_id}/` (relevant once interactive/batch workflows land).

## Storage and deployment

- ~~[Per-group file_system_root](enhancement_file_system_root_per_group_260505.md)~~ — **shipped 2026-05-05** in Phase 1 (commits `phase 1.3`, `phase 1.4`). Resolution chain: group_settings → api_settings → error.
- **Standardize SMB mount point name across all clients** — when moving the backend to the Mac Mini, ensure desktops mount the share at the same POSIX path the backend uses (e.g., `/Volumes/p51_user_data`). Document the mount step in deployment instructions. Defer until the Mac Mini deployment work begins.

## Artifacts

- ~~[Downloaded filename includes run metadata](enhancement_artifact_download_filename_260504.md)~~ — **shipped 2026-05-05** in Phase 2 (commit `phase 2.3`).

## Architecture / data model decisions still open

- ~~**Run config snapshot**~~ — **shipped 2026-05-05** in Phase 1 (commits `phase 1.1`, `phase 1.2`). `workflow_runs.config_snapshot` JSON column captures the user_workflows.config in effect at run start. UI surfacing of the snapshot is deferred (see below).
- **Surface config_snapshot in the UI** — render it on the run detail page. NULL rows (pre-Phase 1) display as "config not captured (older run)."
- **Workflow type dispatch** — currently a 6-branch `if type_id == N` switch on integer PKs. Replace with a registry keyed on a stable type identifier (e.g., a renamed `type_name` that becomes `type_key`).
- **Schema-driven workflow config form** — replace the hardcoded `typeId` switch in `WorkflowConfigForm.tsx` with a form generated from a `config_schema` returned by `/workflow-types`.
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

## Notes

- [User story for workflow categories, types, and user workflows](user_story_workflow_categories_types_and_user_workflows.md) — captures the user-facing model: catalog is fixed, users clone-and-name, multiple instances per type, tune in place, retire by disable.

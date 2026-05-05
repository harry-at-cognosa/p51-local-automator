# Enhancement: Per-group file_system_root

**Date captured:** 2026-05-05

## Decision

Workflow input and output paths should be rooted under a per-group setting, not hardcoded to the project's `data/` directory.

- **Setting location:** `group_settings` (per-tenant), name = `file_system_root`, value = absolute POSIX path on the backend host.
- **Per-run output path:** `<file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/`
  (group_id retained inside the path even though file_system_root is already group-specific — explicit redundancy for safety/clarity.)

## Deployment shapes

- **Desktop / single-user Mac**: `file_system_root = "/Users/harry/p51_output_area"` (or equivalent local path).
- **Mac Mini server on LAN**: `file_system_root = "/Volumes/p51_user_data"` (the SMB share `smb://10.0.100.215/p51_user_data` mounted by macOS at `/Volumes/p51_user_data`).

## Why POSIX paths, not SMB URLs

Python's `open()` and the `os` module do not speak `smb://`. macOS handles the protocol below the filesystem boundary — once mounted, the share is just a path under `/Volumes/`. The application stores and uses the POSIX path. The "this is actually an SMB share" detail is invisible to the application.

## Mount management

Out of scope for the application. The deployment must ensure the share is mounted before the backend starts (e.g., launchd job on the Mac Mini that runs `mount_smbfs` with credentials in Keychain at boot). The application does not attempt to mount on demand.

## UI implication

A future file-picker UI (relevant for type 2 input selection and any other path-config field) should restrict users to browsing only inside `<file_system_root>/{group_id}/{user_id}/...` — they cannot reach into other users' or other groups' subtrees from the picker.

## Replaces

The current convention `data/{group_id}/{user_id}/{workflow_id}/{run_id}/` (constructed in `backend/services/workflow_engine.py:get_run_output_dir`) is replaced by the new path scheme. The `data/` directory at the project root is no longer the output home.

## Input layout

Inputs are colocated under the workflow that uses them:

- Inputs:  `<root>/{group_id}/{user_id}/{workflow_id}/inputs/...`
- Outputs: `<root>/{group_id}/{user_id}/{workflow_id}/{run_id}/...`

Each user_workflow gets its own `inputs/` subdirectory at the workflow level (not per-run), since input files are typically reused across runs of the same workflow. Outputs remain per-run.

## Resolution order for file_system_root

When a workflow run resolves its root path, look up in this order:

1. `group_settings` row with name = `file_system_root` for the workflow's group.
2. If absent, fall back to `api_settings` row with name = `file_system_root` (global default).
3. If both absent, block all group operations with a clear configuration error. No silent fallback to a hardcoded path.

This makes the api_settings global value the platform-wide default for groups that have not customized their root.

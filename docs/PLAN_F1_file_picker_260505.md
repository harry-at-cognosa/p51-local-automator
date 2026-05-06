# F1 Implementation Plan — Sandbox file picker

**Date planned:** 2026-05-05
**Status:** Planned, not yet executed.
**Strategic context:** `/Users/harry/p51_automator_project_info/p521_agentic_workflows/awf1_build_plan_260505.md` — F1 is the first foundation phase before AWF-1 work begins. Closes the BACKLOG's deferred file-picker item; unblocks AWF-1 input rows and the BACKLOG's interactive single-file analyzer / folder-batch analyzer.

## Goal

A reusable file-picker primitive scoped to each user's sandbox inputs area, integrated into the schema-driven config form via two new field types: `file_picker` (single file) and `repeating_rows` (composite rows with sub-fields, used by AWF-1 for the per-table file+description list).

## Design decisions confirmed in `first_agentic_workflow_review_260505.md` §3

- Picker scope: `<file_system_root>/{group_id}/{user_id}/inputs/` — per-user, not per-workflow. A user's CSVs and xlsx files are reusable across workflows.
- File-type filter: csv + xlsx only for v1.
- One row per (file, description) pair, description required to save.
- "Import folder" convenience: separate button that scopes a folder picker to inputs/, auto-adds one row per matching file with empty description.
- Snapshot stores path + sha256 (Snapshot work is in F4 / A1, not F1; F1 just exposes the path).
- Reasonable cap: 10 rows per workflow.

## New design decisions surfaced during planning (need confirmation before execution)

1. **Coexistence with `get_workflow_inputs_dir`.** A per-workflow inputs helper already exists in `backend/services/workflow_engine.py:77` (`<file_system_root>/{group_id}/{user_id}/{workflow_id}/inputs/`) but is not wired into any current workflow. F1 adds a sibling per-user helper `get_user_inputs_dir` that resolves to `<file_system_root>/{group_id}/{user_id}/inputs/`. Both helpers coexist; the per-workflow helper stays available for future workflow types that genuinely want per-workflow scope (e.g., the BACKLOG folder-batch analyzer with its processed-files ledger).

2. **Path-traversal protection at the endpoint.** This is the first code that exposes a filesystem-listing endpoint. The `subpath` query parameter must be normalized and verified to remain inside the user's inputs root. Any `..`-laden subpath returns 400.

3. **Empty-directory rendering.** When the user's inputs/ is empty (or doesn't yet exist), the endpoint auto-creates it (mkdir -p) and returns `[]`. The frontend renders "No files yet. Place files via your SMB share at `<path>`" so the user knows where to put them.

4. **Folder-import semantics.** "Import folder" is a separate button, not an overloaded behavior on file clicks. Clicking the button opens a folder-scoped variant of the picker; the user navigates and clicks a folder; the form receives a list of every csv/xlsx file directly inside that folder (non-recursive for v1). Each file becomes a new row with empty description.

5. **Description-required validation.** Form-level validation is the consumer's responsibility (Workflows.tsx, WorkflowDetail.tsx), not the SchemaConfigForm primitive. F1 ships the field types; the AWF-1 work in A1 wires up the validation. F1 itself does not need to enforce description-required — it just provides the building blocks.

6. **No auth tokens in the listing endpoint URL.** Standard Bearer auth via `Depends(current_active_user)` — no need for the query-param-token pattern that artifacts.py uses (that pattern exists for `<img src>` tags which can't carry a header).

## Commit boundaries

Seven commits. F1.1–F1.4 are independently shippable. F1.5 depends on F1.4. F1.6 depends on F1.5. F1.7 is documentation only.

---

## Commit F1.1 — Backend helper `get_user_inputs_dir`

**Code edit** at `backend/services/workflow_engine.py`:

Add a sibling helper to the existing `get_workflow_inputs_dir`:

```python
async def get_user_inputs_dir(
    session: AsyncSession,
    group_id: int,
    user_id: int,
) -> str:
    """Return the per-user filesystem root for input files reusable across workflows.

    Path layout: <file_system_root>/{group_id}/{user_id}/inputs/

    Files placed here are visible to every workflow owned by this user. Use this
    for input pickers; use get_workflow_inputs_dir() when a workflow needs its
    own private inputs space (e.g., per-workflow processed-files ledgers).
    """
    root = await _resolve_file_system_root(session, group_id)
    path = os.path.join(root, str(group_id), str(user_id), "inputs")
    os.makedirs(path, exist_ok=True)
    return path
```

**Verification:** call from a Python REPL with a session and a real group/user; confirm the path comes back, the directory is created on disk, repeated calls are idempotent.

Reversible — pure additive.

---

## Commit F1.2 — Backend endpoint `GET /api/v1/files/list`

**New file** `backend/api/files.py`:

- `router_files = APIRouter(prefix="/files")`
- `GET /list?subpath=&filter_extensions=` — lists entries under the user's inputs root, optionally narrowed to a subdirectory and filtered by extension.
- Auth: `Depends(current_active_user)`. The user's `group_id` and `user_id` resolve the inputs root; the user can only see their own files.
- `subpath` validation: normalize, reject if it contains `..`, reject if normalized path escapes the inputs root.
- Response shape:
  ```json
  {
    "root_path": "/Users/harry/p51_output_area/2/5/inputs",
    "subpath": "",
    "entries": [
      {"name": "purchases_q3.csv", "kind": "file", "size": 12345, "modified": "2026-05-05T10:30:00Z"},
      {"name": "archive", "kind": "dir", "size": null, "modified": "2026-05-04T08:00:00Z"}
    ]
  }
  ```
- `filter_extensions` is comma-separated (e.g. `csv,xlsx`); when provided, only files matching these extensions appear in the response, but directories are always included so the user can navigate.
- The endpoint creates the inputs root via `get_user_inputs_dir` if it doesn't exist, then returns `[]` on a fresh root.

**Wire-up** in `backend/api/__init__.py`:

```python
from backend.api.files import router_files
api_router.include_router(router_files, tags=["Files"])
```

**Verification:**
- Hit `GET /api/v1/files/list` as an authenticated user; observe the inputs/ directory on disk gets created if absent; response is `{root_path, subpath: "", entries: []}`.
- Drop a `test.csv` into the inputs/ directory; hit the endpoint; the file appears.
- Hit with `?subpath=../../../etc`; expect 400.
- Hit with `?filter_extensions=csv,xlsx`; only csv/xlsx files in `entries`.

Reversible — additive.

---

## Commit F1.3 — Frontend `<FilePicker />` component

**New file** `frontend/src/components/FilePicker.tsx`:

- Bootstrap-styled modal opened via a button labeled "Pick file" or via a controlled prop.
- Props:
  ```ts
  interface Props {
    mode: "file" | "folder";
    filterExtensions?: string[];   // e.g. ['csv', 'xlsx']
    initialSubpath?: string;
    onSelect: (selection: { path: string; name: string }) => void;
    onCancel: () => void;
    show: boolean;
  }
  ```
- Calls `GET /api/v1/files/list?subpath=...&filter_extensions=...` (using the same auth-fetch helper used by other pages — see Workflows.tsx for the pattern).
- Renders a flat list of entries for the current subpath. Directories are clickable to navigate into. A breadcrumb shows the current subpath. A back button navigates up.
- In `mode="file"`, only files are selectable — clicking a file calls `onSelect({path, name})` where `path` is the relative path under the user's inputs root (NOT the absolute server path; the consumer combines with the server root).
- In `mode="folder"`, only folders are selectable. Selecting a folder calls `onSelect({path: subpath, name: subpath_basename})`.
- Empty state: when `entries.length === 0`, render "No files yet. Place files via your SMB share at `{root_path}`."

**Verification:**
- Standalone test: drop the component into a scratch page or storybook-equivalent, supply `mode="file"`, see the modal open and list contents of the user's inputs/.
- Click into a subdirectory; breadcrumb updates; back button works.
- Click a csv file; `onSelect` fires with the right path.

Reversible — additive component, no consumers yet.

---

## Commit F1.4 — `SchemaConfigForm` adds `file_picker` field type

**Code edit** at `frontend/src/components/SchemaConfigForm.tsx`:

- Extend `FieldDescriptor.type` union with `"file_picker"`.
- Add a new optional field `filter_extensions?: string[]` on `FieldDescriptor`.
- In the `renderInput` switch, add a case for `"file_picker"` that renders:
  - The currently-selected file path as text (or "No file selected" placeholder).
  - A "Pick file" button that opens `<FilePicker mode="file" filterExtensions={f.filter_extensions} ... />` and on select stores `{path, name}` into `config[f.name]`.
  - A "Clear" button to unset.
- Stored value shape: `{path: string, name: string}` or `null`.

**Verification:**
- Author a tiny test schema with a single `file_picker` field; render via `SchemaConfigForm`; pick a file; observe the form's config state contains `{path, name}`.

Reversible — additive type. Existing fields unaffected.

---

## Commit F1.5 — `SchemaConfigForm` adds `repeating_rows` field type

**Code edit** at `frontend/src/components/SchemaConfigForm.tsx`:

- Extend `FieldDescriptor.type` union with `"repeating_rows"`.
- Add new optional fields on `FieldDescriptor`:
  ```ts
  row_schema?: FieldDescriptor[];   // sub-fields per row
  min_rows?: number;
  max_rows?: number;
  add_label?: string;               // default: "Add row"
  ```
- In the `renderInput` switch, add a case for `"repeating_rows"` that renders:
  - A list of rows. Each row is a horizontal layout of sub-field renderers (recursively using `renderInput` for each `row_schema` entry).
  - A delete button per row (disabled when `rows.length <= min_rows ?? 0`).
  - An "Add row" button below the list (disabled when `rows.length >= max_rows`).
  - Initial state: `min_rows ?? 1` empty rows.
- Stored value shape: `Array<Record<string, unknown>>` — each row is a dict keyed by sub-field name.

**Verification:**
- Author a test schema with a `repeating_rows` field whose `row_schema` contains one `file_picker` and one `string` (description). Render. Add 3 rows, fill them in. Confirm the form state is an array of three dicts.
- Test min_rows=1, max_rows=10; verify add/delete buttons disable correctly.

Reversible — additive type. Existing fields unaffected.

---

## Commit F1.6 — Folder-import convenience

**Code edit** at `frontend/src/components/SchemaConfigForm.tsx`:

- Within the `repeating_rows` renderer: when the row_schema contains exactly one `file_picker` field, surface an "Import folder" button next to "Add row."
- Clicking opens `<FilePicker mode="folder" filterExtensions={...} />`. On folder select:
  - Backend call: `GET /api/v1/files/list?subpath={folder}&filter_extensions={...}`.
  - For each file entry, append a new row with the `file_picker` field populated and other sub-fields empty.
  - Don't exceed `max_rows`; if the folder has more files than the cap, append until the cap, no warning required for v1 (the user sees the row count; can delete and re-import a subset).
- The button is hidden if the row_schema has no `file_picker` field.

**Verification:**
- Author the test schema from F1.5. Use the folder-import button. Pick a folder containing 3 csv files. Confirm 3 new rows appear with file_picker populated and description fields empty.
- Repeat with `max_rows=2` and a folder containing 5 files; only 2 rows appended.

Reversible.

---

## Commit F1.7 — Documentation + BACKLOG mark

**Update** `docs/BACKLOG.md`:

- Mark "File-picker UI for any path-config field" as shipped (under UI/UX).
- Add a note pointing future authors at the new schema field types.

**Update** `CLAUDE.md` if needed: the data layout section already mentions `data/{group_id}/{user_id}/{workflow_id}/{run_id}/`. Add a one-line note that user inputs live at `<file_system_root>/{group_id}/{user_id}/inputs/`.

No code changes. Reversible.

---

## Risks and mitigations

**Path traversal.** Highest-priority risk for the new endpoint. Mitigation: normalize the subpath, verify the resolved absolute path is a prefix of the inputs root, reject otherwise. Unit test for `..`, absolute paths, symlinked escape attempts.

**Empty inputs/ first run.** The endpoint creates the directory on first access. Hand-tested by deleting `<root>/{group}/{user}/inputs/` and hitting the endpoint — should re-create cleanly.

**SchemaConfigForm consumers.** `Workflows.tsx` and `WorkflowDetail.tsx` import `FieldDescriptor` and pass it through — adding new union variants doesn't break them as long as existing consumers don't switch on the union exhaustively. They don't (verified by grep).

**Multi-tenancy.** `get_user_inputs_dir` resolves through the file_system_root chain (group_settings → api_settings). A user from group 2 cannot see group 3's files because the endpoint computes the root from `current_user.group_id`. The endpoint never accepts a group_id parameter from the client.

**Existing per-workflow helper.** `get_workflow_inputs_dir` is unused today. It stays, with no callers, ready for future workflow types that want per-workflow scope. No risk of confusion as long as the docstrings stay clear about the difference.

**SMB-mount path on the deployed Mac Mini.** The backend writes via the resolved file_system_root, so as long as the share is mounted under the configured root on the server, this works. F1 doesn't introduce new mount-management requirements; it inherits the Phase 1.4 chain.

---

## Commit boundaries summary

Seven commits, each independently shippable and verifiable:

1. F1.1 — Backend helper `get_user_inputs_dir`. Pure additive.
2. F1.2 — Backend endpoint `GET /api/v1/files/list`. Path-traversal-hardened. Auto-creates inputs/.
3. F1.3 — Frontend `<FilePicker />` component. Standalone, modal-based, file or folder mode.
4. F1.4 — `SchemaConfigForm` `file_picker` field type. Single-file selection.
5. F1.5 — `SchemaConfigForm` `repeating_rows` field type. Composite rows with sub-fields.
6. F1.6 — Folder-import convenience button. Bulk-add files from a folder.
7. F1.7 — Docs + BACKLOG mark.

Frontend pages (Workflows, WorkflowDetail) are untouched — the new field types are picked up automatically by the existing `<SchemaConfigForm>` integration. F1 ships zero AWF-1-specific code; AWF-1's A1 phase consumes these primitives via its config_schema.

## Critical files for implementation

- `backend/services/workflow_engine.py` (add `get_user_inputs_dir`)
- `backend/api/files.py` (new)
- `backend/api/__init__.py` (router wire-up)
- `frontend/src/components/FilePicker.tsx` (new)
- `frontend/src/components/SchemaConfigForm.tsx` (add two field types)
- `docs/BACKLOG.md` (mark shipped)

## What gets verified end-to-end before declaring F1 done

1. Author a one-off "test schema" in a scratch workflow type (or directly in a debug page) with a `repeating_rows` field whose `row_schema` is `[{name: "file", type: "file_picker", filter_extensions: ["csv","xlsx"]}, {name: "description", type: "string"}]`.
2. Render the form. Add three rows. For row 1, use the file picker to select a csv from inputs/. For row 2, type a description without selecting a file. For row 3, click "Import folder" and pick a folder containing 2 xlsx files (confirm 2 rows append with file populated, descriptions empty — yielding 5 rows total once F1.6 lands).
3. Confirm the form's config state is the expected `Array<{file: {path, name}, description: string}>`.
4. Confirm the path-traversal guard rejects `?subpath=../../../etc` with a 400.
5. Confirm a fresh user (no inputs/ dir yet) sees the empty-state message and the directory is auto-created server-side.

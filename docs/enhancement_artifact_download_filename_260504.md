# Enhancement: Prefix downloaded artifact filenames with run metadata

**Endpoint affected:** `GET /api/v1/artifacts/{artifact_id}/download` — `backend/api/artifacts.py`
**Frontend trigger:** download links on `/app/runs/:run_id` — `frontend/src/pages/RunDetail.tsx`

## Problem

When a user downloads an artifact from a run, the filename in the download is the artifact's stored filename (e.g., `report.xlsx`, `analysis.json`). Once it lands in their Downloads folder alongside artifacts from other runs / other workflows, there is no way to tell what it came from.

## Fix

The HTTP `Content-Disposition` filename returned by the download endpoint should be:

```
YYMMDD_HHMMSS_run_<run_id>_uwf_<workflow_id>_cat_<category_id>_type_<type_id>_<original_filename>
```

Where:
- `YYMMDD_HHMMSS` — the run's started_at timestamp (zero-padded, local time or UTC — pick one and stay consistent)
- `<run_id>` — `workflow_runs.run_id`
- `<workflow_id>` — `user_workflows.workflow_id` (the user's configured workflow instance)
- `<category_id>` — `workflow_categories.category_id` (resolved via the type)
- `<type_id>` — `workflow_types.type_id`
- `<original_filename>` — the existing artifact filename (preserve extension)

Example:
```
260504_224917_run_56_uwf_131_cat_4_type_4_annual_orders_results.xlsx
```

## Implementation notes

- The on-disk path under `data/{group_id}/{user_id}/{workflow_id}/{run_id}/` does NOT need to change. Only the `Content-Disposition: attachment; filename="..."` header that the download endpoint sends.
- All five IDs/timestamps are reachable by joining `workflow_artifacts → workflow_runs → user_workflows → workflow_types → workflow_categories` from `artifact_id`. One query, no schema change.
- Open question: pick UTC vs local for the timestamp. UTC is safer for a multi-tenant audit story; local is friendlier for single-tenant Mac Mini deployment. Default to local unless we hear otherwise.
- Sanitize `<original_filename>` (replace any spaces / unsafe chars with `_`) so the prefix isn't broken by an existing filename quirk.

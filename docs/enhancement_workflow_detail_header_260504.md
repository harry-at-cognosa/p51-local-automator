# Enhancement: Workflow Detail page header

**Page:** `/app/workflows/:id` — `frontend/src/pages/WorkflowDetail.tsx`
**Date captured:** 2026-05-04
**Screenshot:** `enhancement_workflow_detail_header_260504.png`

## Current state

Page header is one large line with the user-given workflow name (click to edit), then a small "Created M/D/YYYY" line beneath. Workflow category and workflow type are not shown anywhere on the page.

## Desired state

Two lines at the top of the page, both small:

1. **User Workflow Name:** `<current name>` — click to edit
2. **Category:** `<short_name>`  **Type:** `<short_name>`  **Created** `<date>`

The user-given name moves out of the page-title slot and becomes a labeled, smaller-font field. The category/type/created line replaces the current "Created M/D/YYYY" line.

## Why

As more workflow categories and types are added, users won't be able to tell from the page alone which category/type a given workflow instance belongs to. The user-given name is often customized (e.g., "test new ETM versoin - harry - icloud - 7 days") and won't reliably encode the type.

## Affected fields (already in the API response on /workflows/:id)

- `workflow.type.short_name`
- `workflow.type.category.short_name`
- `workflow.name` (user-given)
- `workflow.created_at`

No backend or schema changes required.

# Enhancement: Stack Workflow Detail layout vertically

**Page:** `/app/workflows/:id` — `frontend/src/pages/WorkflowDetail.tsx`
**Date captured:** 2026-05-04
**Screenshot:** `enhancement_workflow_detail_stack_layout_260504.png`

## Problem

The current layout puts Configuration (A) and Run History (B) side by side, with Pipeline Steps (C) under A. When a workflow's `config` JSON contains a long single-line value (e.g., the `query` field in a Type 4 SQL Runner workflow), the Configuration card stretches horizontally and pushes Run History off the right edge of the viewport. On a 2560×1440 monitor this still forces horizontal scrolling.

## Fix

Stack the three sections vertically: Configuration (A) on top, Pipeline Steps (B') in the middle, Run History (C') at the bottom — full width each. No side-by-side columns.

This avoids the horizontal-overflow problem entirely and is more legible for any workflow type since long content (config JSON, future run history with many rows, etc.) just grows downward.

## Notes

- Long single-line strings inside the JSON pretty-print may still overflow horizontally within the Configuration card itself; that's a separate fix (word-break / wrap-anywhere on the `<pre>` block) and is independent of the page-level layout change.
- Order question for the new vertical stack: Configuration → Pipeline Steps → Run History feels right (definition first, then what it does, then what's happened) but is open to revision.

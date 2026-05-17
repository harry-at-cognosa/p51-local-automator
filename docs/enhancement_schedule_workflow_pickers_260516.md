# Enhancement: Scheduling-affordance pickers (Workflows page + Schedules popover)

**Date captured:** 2026-05-16
**Pages affected:**
- `frontend/src/pages/Schedules.tsx` — the existing "+ Schedule a job" picker
- `frontend/src/pages/Workflows.tsx` — adds a new Schedule bulk-action button
- `frontend/src/components/EditScheduleModal.tsx` — reused as-is, no changes

**Backend:** no schema change. `backend/api/workflows.py` may gain one helper to expose "most-recent-completed-run timestamp" per workflow if the list endpoint doesn't already carry it efficiently.

## Problem

There are two distinct paths through the UI where a user might want to schedule a workflow:

1. **From the Schedules page** — clicking **+ Schedule a job** opens a popover that lists eligible workflows to pick from.
2. **From the Workflows page** — staring at the workflow list, the user wants to schedule one of the rows directly without first opening its detail page.

Today only path (1) exists. Path (1)'s picker is also wider than it should be in two ways: it scopes too tightly (caller-owned only, even for group admins / managers who legitimately operate on other group members' workflows) and offers no constraints that would steer the user toward proven-runnable workflows. The combination — wrong scope + no run-history filter + no cap — invites two real mistakes: scheduling someone else's workflow you don't have the auth to run, or scheduling a workflow that's never actually completed once.

Path (2) doesn't exist at all. The fallback today is "open the workflow detail page, then click Edit on its Schedule card" — fine but requires the user to know that affordance exists.

## Design decisions (settled)

These were worked through in the discussion that produced this spec; recording them up front so the implementation isn't re-litigating them.

- **Per-group superuser accounts as the cross-group story.** Operators who need to act in another group create a separate account in that group rather than impersonating across groups via a session-level "effective group" switch. The `is_superuser` flag is reserved for the one account (admin@System) that needs system-wide access; in-group admins use `is_groupadmin=true, is_manager=true, is_superuser=false`. No "effective group" infrastructure is built. The earlier backlog item about this (commit `6444b09`) is superseded by this decision for the picker case; the deeper API-side inconsistency it described is left as a separate concern.
- **Manager and groupadmin treated identically** for this work. Future refinement is possible but not designed.
- **The Schedules-page popover stays a popover; it does not grow into a full filter/search/picker.** Its job is "I'm here on Schedules and want to add a recent, proven workflow quickly." When the popover doesn't show what the user needs, the answer is the Workflows page Schedule button (path 2), not a fancier popover.
- **Apple-Mail / shared-tenant workflows have no per-user auth filter.** A groupadmin can schedule any group member's Apple-Mail workflow because the Mac itself is the auth boundary. Per-user OAuth (Gmail, Google Calendar) is filtered — see below.

## P1 — Schedules-page picker rules

### Scope

Replace `w.user_id === auth.user_id` in `Schedules.tsx:107-115` with role-aware scope:

| Role | What appears in the picker |
| --- | --- |
| Employee | Workflows the caller owns (`user_id === auth.user_id`). |
| Manager / Groupadmin | Workflows whose `group_id === auth.group_id`, regardless of `user_id`. |
| Superuser (admin@System) | Same as groupadmin scoped to their actual `group_id` (which is 1 for the canonical superuser). No cross-group reach from this picker. |

### Auth-aware filter (applied after scope)

Workflows that reference a per-user OAuth credential — Gmail / Google Calendar — appear only if the caller personally owns the relevant `gmail_accounts` row.

```
INCLUDE workflow w if:
   w.config.account_id IS NULL                         (no OAuth needed)
OR w.config.service IN ("apple_mail", "apple_calendar") (Mac-level auth)
OR EXISTS (
     SELECT 1 FROM gmail_accounts ga
      WHERE ga.account_id = w.config.account_id
        AND ga.user_id    = current_user.user_id
   )
```

`config.account_id` is the field set by Track B (Gmail) and Track GC (Google Calendar) forms; `config.service` discriminates apple vs google. Workflows without an email/calendar dependency at all (Type 2, Type 4, Type 7) skip the OAuth check entirely.

### Schedulability + state filter

Unchanged from today plus one refinement:

- `w.type.schedulable !== false` (Type 7 excluded as it ships with `schedulable=FALSE`).
- **Exclude only schedules currently in `Active` state.** Today's filter is `!w.schedule` (no schedule object at all). Loosened to also include workflows whose schedule is Paused, Expired, or one-time Completed/Failed/Done — picking one of those effectively replaces the prior schedule. Statuses are derived using the same logic as `Schedules.tsx:33-51`.

### Run-history filter

Include only:

- Workflows that have **at least one `workflow_runs` row with `status = 'completed'`**, OR
- Workflows with **zero `workflow_runs` rows** (never run).

Workflows whose only run history is failed/running are excluded. This is by design: if the user couldn't get a manual Run Now to succeed, they shouldn't be able to put it on a cron from this affordance. If they later fix the workflow and Run Now succeeds once, it becomes eligible.

### Sort + cap

- Sort key: most-recent-completed-run `started_at` descending. For never-run workflows, fall back to `created_at` descending. The two sources intermingle into one DESC list.
- Cap: 5 entries displayed.

### Heading copy

The picker's modal title and body subtitle make the constraints visible so the cap doesn't feel arbitrary:

> **Title:** Schedule which workflow?
> **Subtitle (small, under title):** Never-run or successfully-run workflows only, five most recent. To pick from any workflow you can see, use the Schedule button on the Workflows page.

## P3 — Workflows-page Schedule button

### Surface

Adds a `Schedule` button to the bulk-action row above the VCR pager on `frontend/src/pages/Workflows.tsx` — the same row that already houses Select-all-on-page / Delete Selected and uses the existing `selectedIds` Set in `workflowsStore`.

```
┌─────────────────────────────────────────────────────────────────────┐
│  [Type filter ▾]            [☑ Select all on page] [Delete Selected]│
│                                                  [Schedule]          │
│                                              ◀ ◀◀ Page 1 of 2 ▶▶ ▶   │
└─────────────────────────────────────────────────────────────────────┘
```

### Behavior

- Enabled only when **exactly one** row in `selectedIds` is selected.
  - 0 selected → disabled, tooltip: "Select a single workflow to schedule it."
  - 2+ selected → disabled, tooltip: "Schedule supports one workflow at a time. Select just one."
- On click, opens `EditScheduleModal` inline on the Workflows page with the selected workflow's id + name. No navigation, no popover. Same modal as WorkflowDetail and the Schedules-page popover use today.
- On Save, the workflow's schedule is updated via the existing `PUT /workflows/{id}` flow that `EditScheduleModal` already calls; the modal closes; the Workflows list re-fetches so the row reflects the new schedule state.

### Eligibility hint (optional polish, not blocking)

The button can stay enabled regardless of run history (the user can always try to schedule; the backend accepts it). If we want symmetry with P1's "never-run or successfully-run only" rule, the button could become disabled on a single-selected workflow whose only runs are failed, with a tooltip explaining why. **Recommendation: don't add this guard in P1+P3.** The Workflows page is the documented escape hatch precisely for cases the popover hides; making it equally restrictive defeats the purpose. Let the user schedule any workflow they can see.

## What "ineligible" means by surface

| Surface | Scope filter | Auth filter | Run-history filter | Schedule-state filter | Sort + cap |
| --- | --- | --- | --- | --- | --- |
| Schedules popover | Role-aware (above) | Apply | Apply | Active excluded | DESC, cap 5 |
| Workflows page Schedule button | Whatever role lets caller see | n/a | n/a | n/a | n/a (single-row UX) |

The asymmetry is the point: the popover is a *quick* affordance for the common case; the Workflows page is the *complete* affordance for everything.

## Backend touchpoints

- **`backend/api/workflows.py` — `list_workflows`** (the endpoint feeding the popover). Today it returns one row per workflow with `latest_run_status` and `latest_started_at` from a `DISTINCT ON (workflow_id)` subquery over **non-archived** runs of any status. The popover needs **most-recent-completed-run** specifically. Two ways to surface it:
  - **A. Add a second column to the existing query** — `latest_completed_run_started_at`, computed via a parallel subquery filtered to `status = 'completed'`. Cheap and keeps the popover client-side.
  - **B. Add a query parameter** `?eligible_for_schedule_picker=1` that returns the already-filtered, already-sorted, already-capped 5-row list. Server-side filtering, less for the client to compute, but a more single-purpose endpoint.
  - **Recommendation: A.** The endpoint is already general-purpose; one extra column is cleaner than a special-case query parameter. The popover does the final filter + sort + cap in TypeScript against the same shape the rest of the page uses.
- **`backend/services/scheduler_service.py`** — no change.
- **`backend/db/models.py`** — no change.

## Frontend touchpoints

- **`frontend/src/pages/Schedules.tsx`**
  - Replace the filter chain in `openPicker()` (lines 101-122) with the role-scope + auth + run-history + state-filter pipeline.
  - Add sort by most-recent-completed-or-created descending; slice to 5.
  - Update the modal title and add the subtitle copy.
  - Stores: read the current user's `auth.is_groupadmin`, `is_manager`, `is_superuser`, `user_id`, `group_id` from the existing auth store.
- **`frontend/src/pages/Workflows.tsx`**
  - Add Schedule button to the bulk-action row.
  - Add `useState<{ workflow_id: number; name: string } | null>` for the modal target.
  - Render `<EditScheduleModal>` when state is non-null, passing `onSaved` that re-fetches the workflow list and clears state.
- **`frontend/src/components/EditScheduleModal.tsx`** — no change. Already accepts `workflowId` and `workflowName` props from both WorkflowDetail and the Schedules-page popover; the new Workflows-page caller plugs in the same way.

## Implementation plan

Single phase, three sub-steps. The plan keeps the existing popover working at every step (no UX regression while it's being changed).

### Step 1 — Backend list-endpoint extension

- Add `latest_completed_run_started_at` to `UserWorkflowListRead` schema.
- Update `list_workflows` query to compute it via a sibling subquery to the existing `latest_runs` one, filtered to `status = 'completed'`. Same `DISTINCT ON` pattern.
- No frontend changes yet; existing popover continues to use the old fields (`!w.schedule` filter), nothing breaks.

### Step 2 — Schedules popover tightening (P1)

- Rewrite `openPicker()` to consume the new field and implement scope + auth + run-history + state filter + sort + cap.
- Update modal title and subtitle copy.
- Verify the popover behaves correctly for: employee, manager, groupadmin, superuser (admin@System).
- Verify auth-filter for a Gmail-using workflow: it should appear for `cogmgr` only if `cogmgr` owns the `gmail_accounts.account_id` referenced; should *not* appear for another groupadmin in the same group who hasn't connected their own Google account.

### Step 3 — Workflows page Schedule button (P3)

- Add the Schedule button + its enabled/disabled logic + tooltips.
- Wire up `EditScheduleModal` instance with state for the target workflow.
- On Save, re-fetch the workflow list so the row reflects the new schedule.
- Verify the round-trip: select one row, Schedule, Save, see the row's schedule field update.

### Step 4 — Heading copy verification

- Confirm the picker subtitle's "Schedule button on the Workflows page" actually exists by the time Step 2 ships. (If Step 3 ships first, this is automatic. If Step 2 ships first, the subtitle's link is misleading until Step 3 lands.)

## Non-goals (explicitly out of scope)

- **Cross-group superuser scheduling from the picker.** Deferred per the per-group-account decision above; not in P1, not in P3.
- **Pre-population of the Schedules-page popover from the Workflows page.** Considered and rejected: the inline modal on the Workflows page is simpler and doesn't require coupling the two pages.
- **Failure-history workflows in the picker.** Excluded by design. Workflows with failed-only history must succeed via Run Now once before becoming eligible.
- **A live-progress / streaming affordance for in-flight schedules.** Separate concern; lives in the existing AG-UI evaluation note (commit `7bea494`).

## Verification

Manual UAT (no automated tests proposed for this UI work):

1. Log in as `admin` (group 1). Open Schedules → + Schedule a job. Verify picker shows only group-1 workflows that have at least one completed run or none, sorted descending, capped at 5. Verify subtitle copy renders.
2. Log in as `cogmgr` (group 2). Same as above for group 2. Verify a Gmail-using workflow owned by another group-2 user appears only if `cogmgr` has connected the same Google account.
3. Log in as `cogsu` (group 2, groupadmin/manager, not superuser per the decision above). Verify same group-2 visibility as `cogmgr`.
4. Open Workflows page. Select one workflow row → Schedule button enabled. Select two → disabled with tooltip. Select zero → disabled with tooltip.
5. Click Schedule with one selected → EditScheduleModal opens with the right workflow. Save a one-time schedule. Verify the row's schedule field updates and the workflow now appears on the Schedules page.
6. From the now-updated Schedules page, verify the workflow appears in the schedules table with the correct fire-time and is *excluded* from a subsequent + Schedule a job picker open (because its schedule is now Active).

## Open items

None at spec time. Implementation may surface small wording choices (button label "Schedule" vs "Schedule…", tooltip phrasing) that should be settled inline during the build.

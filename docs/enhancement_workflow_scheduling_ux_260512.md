# Enhancement: Workflow Scheduling UX

**Date captured:** 2026-05-12
**Pages affected:** `/app/workflows/:id` — `frontend/src/pages/WorkflowDetail.tsx`
**Backend:** `backend/services/scheduler_service.py`, `backend/db/models.py` (`UserWorkflows.schedule` JSON column)

## Problem

Today, scheduling a workflow requires hand-editing a JSON dict on a database row or hitting the API directly. The frontend only displays the current schedule as read-only JSON when one happens to be present. The backend understands a single shape — `{hour, minute}` in **UTC** — and runs the workflow daily at that time. The `days_of_week` field documented in the scheduler's docstring is not actually implemented in the polling loop.

We want a first-class scheduling UX that supports:

- **One-time** — run once at a specified local date/time.
- **Recurring** — within a date range, on a frequency the user picks.
  - Workdays (Mon–Fri)
  - Every day
  - Specific days of week (one or more)
  - Every N weeks on one or more days of week (N ∈ {2, 3, 4}; weekly is N=1)

…all of which the user picks in their **local time**, with the backend converting to UTC at each fire to handle DST correctly.

## Proposed schedule shape

Stored in the existing `UserWorkflows.schedule` JSON column. Discriminated by a `kind` field so the polling logic can branch cleanly.

### One-time

```json
{
  "kind": "one_time",
  "at_local": "2026-05-15T08:00",
  "tz": "America/Los_Angeles"
}
```

Auto-disables (`enabled=false`) after firing. No retry on miss.

### Recurring

```json
{
  "kind": "recurring",
  "starts_on": "2026-05-15",
  "ends_on":   "2027-05-15",
  "hour": 8,
  "minute": 0,
  "tz": "America/Los_Angeles",
  "days_of_week": [0, 1, 2, 3, 4],
  "week_interval": 1
}
```

- `days_of_week`: list of 0–6 where **0=Monday, 6=Sunday** (ISO weekday).
- `week_interval`: 1=weekly, 2=biweekly, 3, or 4. Anchored to `starts_on` (week 0 is the week containing `starts_on`; fires only when `(weeks_since_starts_on % week_interval) == 0`).
- `ends_on` is inclusive; max range one year past `starts_on`.

### Frequency presets → underlying shape

The UI exposes presets; the stored shape is always the same dict.

| Preset | days_of_week | week_interval |
| --- | --- | --- |
| Workdays | [0,1,2,3,4] | 1 |
| Every day | [0,1,2,3,4,5,6] | 1 |
| Specific days (user picks) | user's selection | 1 |
| Every N weeks on day(s) (user picks N and days) | user's selection | N |

### Backwards-compat

Existing rows have just `{hour, minute}`. The polling loop will treat any row lacking a `kind` field as `kind: "recurring", days_of_week: [0..6], week_interval: 1, tz: "UTC"` — preserving today's "fire daily at UTC hour" behavior. Existing schedules continue to work; rewrite is optional.

## Backend changes

In `scheduler_service.py`:

1. **Owner-active gate** (new, first thing checked). Join `UserWorkflows` to `api_users` and skip any schedule whose owner has `is_active=false` or `deleted=1`. Disabled or deleted users' workflows do not fire, even if `enabled=true` on the workflow row. This is the safety net for offboarding.
2. **Per-fire timezone resolution.** For each schedule, compute "now" in the schedule's TZ (via `zoneinfo`, stdlib). Match `hour`/`minute` against TZ-local now, not UTC now. DST handled by `zoneinfo` automatically.
3. **Date-range gate.** Skip if today (in schedule's TZ) is outside `[starts_on, ends_on]`.
4. **Weekday gate.** Skip if today's weekday isn't in `days_of_week`.
5. **Week-interval gate.** Compute `weeks_since = (today - starts_on).days // 7`; skip unless `weeks_since % week_interval == 0`.
6. **One-time path.** Match `at_local` against TZ-local now (hour and minute). On fire, set `enabled=false` to prevent re-fire.
7. **Auto-disable on expiry.** Once a recurring schedule's `ends_on` is in the past (in its TZ), set `enabled=false` on the next poll.
8. **Dedup.** Keep the existing once-per-UTC-day `last_run_at` check, but compare against the schedule's TZ instead of UTC — otherwise an 8 PM PT schedule could fire twice if the UTC date rolls.

In `UserWorkflowUpdate` (`backend/db/schemas.py`): no schema change needed — `schedule: dict | None` accepts the richer shape as-is. Optional: add a Pydantic validator on save to reject malformed shapes (better than discovering the bug at fire time).

Optional: a new endpoint `POST /api/v1/workflows/{id}/schedule/preview` that returns the next N fire times for a candidate schedule shape — feeds the "Next fires" preview in the UI. Cheap to compute, makes the form trustworthy.

## UI surface

Two entry points, one modal:

- **WorkflowDetail page** — Schedule card on the workflow's own page, with an Edit button (the path you take when you're already looking at the workflow you just finished testing).
- **Schedules page** (new, `/app/schedules`) — a dedicated cockpit listing every scheduled workflow visible to the user, with edit / pause / resume / cancel actions inline and a sense of the broader schedule load (the "background of existing jobs" so users see what else is firing around the same time before piling on).

Both surfaces open the same Edit Schedule modal. The workflow lifecycle is:

1. Owner creates the workflow via the existing Workflows page modal.
2. Owner tests it via **Run Now** until satisfied.
3. Owner opens the Schedule editor (from either entry point) and turns it on.

### Schedules page (new)

Reached via the main nav. Scoped to the caller's permissions:

- Employee: their own scheduled workflows.
- Groupadmin: theirs by default; toggle to view all in their group.
- Superuser: same, with an additional toggle for cross-group.

Layout — a single table, one row per scheduled workflow:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Schedules                                              [ + Schedule a job ]  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ☑ Show paused   ☐ All users in my group  (groupadmin)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ Workflow              │ When                  │ Next fire        │ Actions   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Apple Mail digest     │ Workdays at 8:00 AM   │ Mon May 18 8:00  │ Edit Pause│
│ Weekly SQL report     │ Mondays at 9:00 AM    │ Mon May 18 9:00  │ Edit Pause│
│ Apple Card alerts     │ One-time May 20 10am  │ Wed May 20 10:00 │ Edit Cancel│
│ ─ paused ─            │                       │                  │           │
│ Calendar digest (old) │ Every day 7:00 AM     │ — (paused)       │ Resume Del│
└──────────────────────────────────────────────────────────────────────────────┘
```

- **+ Schedule a job** button opens a workflow-picker modal (lists workflows the user owns that don't yet have a schedule) → on select, drops into the Edit Schedule modal pre-populated for that workflow.
- **Pause** sets `enabled=false`; **Resume** sets `enabled=true`; **Cancel** clears the schedule (sets `schedule=null`, leaves the workflow itself intact); **Edit** opens the modal.
- One-time schedules are visually flagged ("One-time" badge or the "auto-disables after firing" note in the row's expanded state).
- Rows are sorted by **Next fire** ascending — the most imminent at the top is the "background" the user is implicitly checking against when they add a new one.

Future polish (Phase S3): swap or augment the table with a 7-day calendar grid showing fire times across all visible schedules, for a denser background-load view.

### Card on the workflow detail page

```
┌────────────────────────────────────────────────────────────┐
│ Schedule                                          [ Edit ] │
├────────────────────────────────────────────────────────────┤
│ Every workday at 8:00 AM PDT                               │
│ From May 15, 2026 until May 15, 2027                       │
│ Next run: Mon, May 18 at 8:00 AM PDT                       │
└────────────────────────────────────────────────────────────┘
```

For one-time:

```
│ One-time: Sat, May 15 2026 at 8:00 AM PDT                  │
│ Will auto-disable after firing.                            │
```

For unscheduled:

```
│ Not scheduled — runs only via Run Now or API.              │
```

The human-readable summary is rendered client-side from the JSON; no backend formatting endpoint needed.

### Edit Schedule modal

```
┌──────────────────────────────────────────────────────────────────┐
│ Schedule: <Workflow Name>                                  [X]   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Mode:  ○ Not scheduled                                          │
│         ○ One-time                                                │
│         ● Recurring                                               │
│                                                                  │
│  ───── When (recurring) ───────────────────────────────────       │
│                                                                  │
│  Frequency: [ Workdays (Mon–Fri)              ▾ ]                 │
│              Workdays (Mon–Fri)                                   │
│              Every day                                            │
│              Specific days of week                                │
│              Every N weeks on specific day(s)                     │
│                                                                  │
│  Time of day: [ 8:00 AM ▾]    Your local time (PDT)               │
│                                                                  │
│  Date range:                                                      │
│    Start: [ 2026-05-15 ]   (default today)                        │
│    End:   [ 2027-05-15 ]   (max one year out)                     │
│                                                                  │
│  ───── Next fires ─────────────────────────────────────           │
│  • Mon, May 18 2026 at 8:00 AM PDT                                │
│  • Tue, May 19 2026 at 8:00 AM PDT                                │
│  • Wed, May 20 2026 at 8:00 AM PDT                                │
│  • Thu, May 21 2026 at 8:00 AM PDT                                │
│  • Fri, May 22 2026 at 8:00 AM PDT                                │
│                                                                  │
│                                       [ Cancel ]  [ Save ]        │
└──────────────────────────────────────────────────────────────────┘
```

#### Variants per Frequency

- **Specific days of week:** show 7 checkboxes (`Mon Tue Wed Thu Fri Sat Sun`) below the dropdown.
- **Every N weeks on specific day(s):** show "Every [ 2 ▾] weeks on" + 7 checkboxes. Dropdown: 2, 3, 4.
- **Workdays / Every day:** no extra controls.

#### One-time variant

Replaces the "When (recurring)" section:

```
│  ───── When (one-time) ────────────────────────────────────       │
│                                                                  │
│  Run once on [ 2026-05-15 ] at [ 8:00 AM ▾]                       │
│              Your local time (PDT)                                │
│                                                                  │
│  Next fires:                                                      │
│  • Sat, May 15 2026 at 8:00 AM PDT                                │
```

#### Not-scheduled variant

```
│  This workflow runs only when you click "Run Now" or trigger      │
│  it via API. Switch to One-time or Recurring above to schedule.    │
```

### Timezone surface

- Default to the browser's IANA TZ (`Intl.DateTimeFormat().resolvedOptions().timeZone`). Display as e.g. "Your local time (PDT)" — abbreviation derived client-side. Stored as the IANA name so DST switches are handled.
- No timezone override in v1. Power users can edit the JSON via API if needed. Per-user TZ as a profile setting is a future enhancement.

## Edge cases

- **DST transitions.** Storing local time + TZ + converting at fire time means an "8 AM PT" schedule is always 8 AM PT, never drifts. The only ambiguity is the 1 AM hour during fall-back, which doesn't apply to 8 AM. (If someone schedules 1:30 AM, document that on DST fall-back day it fires once — the second 1:30 AM is suppressed by the dedup.)
- **Server downtime at fire time.** Job is missed silently; no retry. Documented limitation of in-process APScheduler. (Switch to a persistent job store + missed-job catch-up is a separate, larger enhancement.)
- **Multiple days + N-week interval.** The week-interval applies uniformly to the set of days. e.g., "every 2 weeks on Mon and Wed" fires on Mon and Wed of weeks 0, 2, 4… counting from `starts_on`.
- **End-of-month, end-of-year, 1-year max** — entirely date-math on `starts_on` / `ends_on`. No special handling for months; this isn't a "monthly on the 1st" feature.
- **Type non-schedulable.** Card and modal both hidden when `workflow_type.schedulable === false` (e.g., AWF-1 Data Analyzer).
- **Once-per-day dedup with `every day` + `week_interval=2`.** Dedup still trips per-day; the week-interval gate ensures the off-weeks don't fire.

## Phased build plan

Designed so each phase is shippable and the existing `{hour, minute}` schedules keep working throughout.

### Phase S1 — Backend: data model + polling logic

- Implement the richer polling logic in `scheduler_service.py` (TZ resolution, date-range gate, weekday gate, week-interval gate, one-time, auto-disable on expiry).
- Backward-compat shim for legacy `{hour, minute}` rows.
- `POST /workflows/{id}/schedule/preview` returning next-N fires for a candidate shape (so the UI can show the preview).
- Pydantic validator on `UserWorkflowUpdate.schedule` rejecting malformed shapes.

### Phase S2 — Frontend: card, modal, and Schedules page

- Build the Edit Schedule modal with Mode toggle and per-mode variants. Wire up Preview to the new backend endpoint.
- Replace WorkflowDetail's Schedule card with a human-readable summary + Edit button that opens the modal.
- Add the `/app/schedules` page: list of scheduled workflows with edit / pause / resume / cancel actions, "+ Schedule a job" button opening the workflow-picker → modal flow.
- Main-nav entry for the new page.
- Use browser-detected IANA TZ; no override control yet.

### Phase S3 — Polish (optional, after dogfooding)

- Indicator on the workflows-list page that a row is scheduled (small clock icon + "next: …" tooltip).
- Calendar-grid view on the Schedules page (7-day window across all visible schedules) for denser background-load awareness when many workflows are scheduled.
- Bulk "pause all schedules" toggle in Group Settings (operator panic button).
- Per-user default TZ stored on the user record (replaces browser detection).
- Missed-job catch-up if the server was down at fire time (requires APScheduler job store on disk, larger change).

## Decisions

- **Who can schedule.** Any user can schedule their own workflows; workflow ownership is the only gate. Schedule edits on the Schedules page follow the same rule — owner can edit/pause/cancel; groupadmin/superuser see + manage others' via the role-scoped toggles.
- **Disabled or deleted users.** Their workflows do not fire, regardless of the `enabled` flag on the workflow row. Enforced in the scheduler's polling loop (gate 1). When a user is later re-activated, their existing schedules resume firing automatically — no per-schedule reset needed.
- **Schedules nav entry is always visible** to every authenticated user. The page itself shows an empty-state message when the user owns nothing schedulable; that's a better discovery path than hiding the link.
- **Calendar/holiday awareness.** Out of scope. Workdays = Mon–Fri, no national holiday or per-org calendar.
- **Multi-fire per day.** Not supported in v1 (e.g., "8 AM and 4 PM"). If needed later, that's a list-of-hour-minutes shape inside the recurring kind — straightforward to add.

## Open questions

- **Friendly summary copy.** "Every workday at 8 AM PDT" vs "Mon–Fri at 8:00 AM (Pacific)" — small wording choice, easy to iterate after building.

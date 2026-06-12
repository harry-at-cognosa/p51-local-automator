# Plan — Calendar Digest with Context (new workflow Type 9)

Date: 2026-06-11

## Context

The existing Calendar Digest (Type 3) uses the LLM to assign per-event importance, detect conflicts, and write prep notes. Run 159 of workflow 163 demonstrates the failure mode: "Tirzep Shot" (a self-administered injection reminder) is tagged `high` importance, flagged as a conflict with an HVAC service appointment, and given a fabricated "bring insurance card, arrive early" note. The LLM has no real basis for any of this — only the event title — so the output is decorative guesswork that the user has to mentally filter out.

This plan introduces a new workflow Type 9, "Calendar Digest with Context," that:
- Lets the user provide a free-form context document describing the digest's job
- Lets the user declare event-name substrings that mark events as point-in-time reminders (excluded from conflict math and importance scoring)
- Lets the user declare cross-calendar synonym groups (collapse duplicates)
- Replaces LLM-guessed importance with a typographic convention in the event title (`*important*`, `|tentative|`)
- Replaces LLM-guessed conflicts with deterministic interval math and a visual time grid
- Narrows the LLM's job to writing the top-of-digest summary paragraph, primed by the context document

Type 3 stays in place. Workflow 163 keeps running. Users opt into Type 9 by creating new workflows on it.

## Architecture

Three stages, in order:

### Stage 1 — Event prep (deterministic)
- Fetch events for the next `days` (≤ 7) from the configured service (`apple_calendar` or `google_calendar`)
- Parse event titles for importance markers:
  - `*Title*` → `importance = "important"`, stripped title used downstream
  - `|Title|` → `tentative = true`, stripped title used downstream
  - Both markers can coexist; both apply
- Classify each event as a reminder if its title (after marker stripping) contains any substring from `reminder_patterns` (case-insensitive)
- Collapse synonym matches: for each day, group events whose titles match the same `synonym_groups` entry. The retained event is from the first-listed calendar (per `calendars` config order or `calendar_ids` order); the others are dropped but their calendars are accumulated as an `also_on` list. The retained event's time range becomes `[earliest_start, latest_end]` across the group members.

### Stage 2 — Conflict detection + visual rendering (deterministic)
- Run interval-overlap math across all non-reminder events to identify true conflicts (used for visual emphasis only — no LLM "conflict" output)
- Render the 7-day-or-fewer grid as `calendar_digest.png` (matplotlib):
  - X-axis: one column per day; two-line header — date number on top, weekday name beneath (e.g. `15` / `Mon`)
  - Y-axis: continuous time scale from 7am to 8pm with row labels `before 7`, `9`, `11`, `1`, `3`, `5`, `7`, `later` placed at the hour midpoints
  - Events render as rectangles spanning their actual start→end times
  - Important events: bold border + light fill
  - Tentative events: dashed outline
  - Reminders: thin dot (or short horizontal tick) at the start time, regardless of nominal duration; if a start+stop both exist, render a slim vertical line spanning the time
  - Events earlier than 7am or later than 8pm clip into stub rows at the top/bottom
  - Synonym-collapsed events render once with a small "+N" badge

### Stage 3 — LLM summary (narrow)
- A single LLM call writes one paragraph of summary
- The system prompt contains the user's `context_text` verbatim, framed as "Here is the job of this digest: …"
- The user prompt contains the curated, post-collapse event list with markers parsed out — no raw titles
- The LLM is instructed to write a short overview paragraph only — no per-event tags, no conflict lists, no urgent_items lists, no notes

## Config schema

```jsonc
{
  "service": "apple_calendar",        // or "google_calendar"
  "calendars": ["Work", "Family"],    // apple_calendar
  "account_id": 12,                   // google_calendar
  "calendar_ids": ["primary"],        // google_calendar
  "days": 7,                          // 1..7
  "context_text": "This is my home/personal digest. The household consists of...",
  "reminder_patterns": [
    "Tirzep",
    "Repatha shot"
  ],
  "synonym_groups": [
    ["Trader Joes", "TJ", "TJ's"],
    ["meet doug", "Doug 1:1", "Doug sync"]
  ],
  "email_results": {
    "enabled": true,
    "artifact_kinds": ["digest_md", "digest_png"]
  }
}
```

Matching rules:
- `reminder_patterns`: substring, case-insensitive, contains-any-of
- `synonym_groups`: substring, case-insensitive; an event matches a group if its title contains any phrase from the group; group membership is mutually exclusive — if an event title matches multiple groups, the first listed group wins (deterministic)

## Files to create / modify

### Backend

- `backend/services/workflows/calendar_context_digest.py` — NEW. Runner. Three stages described above. Same `async def run_calendar_context_digest(session, workflow, trigger)` signature as the existing runner.
- `backend/services/workflows/_calendar_grid.py` — NEW. Pure matplotlib rendering helper. Inputs: list of curated events, days, output path. Output: PNG.
- `backend/alembic/versions/<new>_seed_type_9_calendar_context_digest.py` — NEW migration. Inserts the `workflow_types` row for type_id=9 with:
  - `schedulable=true`
  - `emailable_results=true`
  - `config_schema=NULL` (hand-tuned form, not schema-driven)
  - Name: "Calendar Digest with Context"
  - Description, default config matching the schema above
- `backend/services/results_email.py` — extend `ARTIFACT_KINDS_BY_TYPE` with key 9: `{"digest_md": r"calendar_digest\.md$", "digest_png": r"calendar_digest\.png$"}`. Add labels.
- `backend/api/workflows.py` — extend the `_run_workflow_background` dispatch table to route `type_id == 9` to the new runner.
- `backend/__init__.py` — bump `__version__` per CalVer.

### Frontend

- `frontend/src/components/WorkflowConfigForm.tsx` — add a `Type9CalendarContextForm` branch. Reuses the existing service/calendar/account/calendar-ids picker logic from Type 3 (extract it into a shared sub-component if cleanly possible; otherwise copy-and-adapt). Adds three new fields below the picker:
  - `days` number input, 1..7
  - `context_text` textarea, ~8 rows, with help text describing what to put in it (the digest's job, household/team context, anything the LLM should know when writing the summary)
  - `reminder_patterns` — one substring per line in a textarea (parsed to list on save; rendered from list on load); brief help text with examples
  - `synonym_groups` — repeating rows; each row is a textarea or comma-separated input listing the synonyms in the group; "+ Add group" button below; brief help text with examples
  - The existing `EmailResultsSection` is rendered below via `wrapWithEmail`.
- `frontend/src/stores/workflowsStore.ts` — no change expected (the WorkflowType interface already carries `emailable_results`, `email_artifact_kinds`, `schedulable`).
- Past Runs / Workflow Detail UIs — no change expected. PNG artifacts already render inline via the existing artifact view.

## Existing patterns reused

- Type 3 service/calendar picker UI in `WorkflowConfigForm.tsx` for the dynamic calendar dropdowns (apple_calendar list + google_calendar account/calendar selection)
- Type 8 hand-tuned form skeleton (`Type8EmailReaperForm`) for the wrapping pattern of a single-typeId form with sub-sections
- `EmailResultsSection` + `wrapWithEmail` already in WorkflowConfigForm.tsx
- Self-describing artifacts: `build_artifact_meta` + `wrap_json` / `wrap_markdown` from `backend/services/artifact_meta.py`; PNG attribution footer via matplotlib `fig.text` (same pattern as Type 2's chart artifacts)
- `_run_workflow_background` hook in `backend/api/workflows.py` handles the email send post-runner — Type 9 inherits this automatically because it's wired into the same dispatch.
- `engine.create_run` / `start_step` / `complete_step` / `complete_run` / `record_artifact` / `get_run_output_dir` lifecycle (same as Type 3 runner)
- `llm_service.judge_structured` is overkill here (no structured output needed); use a direct `llm_service.complete_text`-style call (or whatever the simplest single-paragraph call is — verify the existing helper names during implementation)

## Edge cases + decisions baked in

- A reminder event with `*Tirzep Shot*` markers: importance markers are parsed first, the cleaned title is `Tirzep Shot`, which still matches the reminder pattern. Reminder classification wins — the event renders as a dot (not a bold-bordered box). Importance markers on reminders are effectively ignored.
- A synonym-collapsed group where one member is important and another isn't: the retained event keeps the first-listed-calendar member's markers. (If the user marks importance differently across calendars, the calendar order decides.)
- Synonym-collapsed group spanning calendars where one member is a reminder pattern and another isn't: reminder wins (the collapsed event renders as a dot).
- Events with the same name on the same day but in only one calendar (true duplicates within one calendar): not collapsed — synonym collapse is cross-calendar only.
- An event title that's only whitespace after stripping markers: treated as `(untitled)`.
- `context_text` is empty: the LLM prompt frames it as "(No specific context given — write a neutral one-paragraph overview.)"
- `reminder_patterns` and `synonym_groups` are empty: all events are eligible for the conflict-emphasis pass and none are collapsed — the digest still works.
- `days` > 7 in saved config: clamp to 7 at runtime, log a warning.
- Event before 7am or after 8pm: render in clipped stub row at top or bottom. If the event spans across the visible window (e.g. 6:30am–9am), draw it from the stub row top down through to its real end.

## Verification

1. Migration installs cleanly. `alembic upgrade head` succeeds; `workflow_types` has a new row for type_id=9 with `schedulable=true`, `emailable_results=true`.
2. Dashboard's "Standard Workflow Types" section shows "Calendar Digest with Context" as a creatable type.
3. Creating a new Type 9 workflow renders the hand-tuned form: service picker, calendar selector, days input, context_text textarea, reminder_patterns textarea, synonym_groups repeating-rows editor, EmailResultsSection at the bottom.
4. Recreate a configuration equivalent to workflow 163 (Work + Family, 4 days) with `reminder_patterns=["Tirzep", "Repatha shot"]` and `synonym_groups=[]` and empty `context_text`. Run manually. Verify:
   - `calendar_digest.md` opens with a one-paragraph LLM summary, then the markdown-table grid, then chronological event list
   - `calendar_digest.png` shows the grid with weekday/date headers on top and time row labels down the left
   - Tirzep Shot appears as a thin marker, not a box; is not labeled `high`; is not in any conflict report
   - HVAC check is a full box; the webinar is a full box; they appear as adjacent or overlapping based on actual times — the reader judges, the digest does not assert
5. Add `synonym_groups=[["Trader Joes", "TJ"]]` and put two same-day events titled "TJ run" (Family) and "Trader Joes" (Work). Run. The PNG and the chronological list show one event, marked `(also on Work)`, with the union time range. The first-listed calendar wins as expected.
6. Add `context_text` describing a specific scenario (e.g. "This is my home digest. My partner is traveling Mon-Wed; ignore her calendar items"). Re-run. The summary paragraph references the context appropriately.
7. Mark an event in Calendar with `*` around its title. Verify PNG shows it with bold border + fill; markdown table shows it bolded. Mark another with `|` pipes around it; verify dashed outline in PNG.
8. Schedule the new Type 9 workflow. Wait for the scheduled run; verify it runs through `_run_workflow_background` and email delivery succeeds (matches Type 3 today).
9. Try `days=10` saved into config; verify runtime clamps to 7 and logs a warning.
10. Try `days=1`; verify the PNG renders as a single-column grid.
11. With `email_results.enabled=true` and `artifact_kinds=["digest_md","digest_png"]`, verify the outbound email arrives with both the MD and PNG attached.
12. Regression: Type 3 (workflow 163) still works unchanged. Its config form is untouched; its scheduled run still fires; its artifacts still render with the old LLM-driven conflict/importance/notes content.

## Open decisions / risks

- The grid axis is a continuous time scale from 7am–8pm with hour labels at 9/11/1/3/5/7. The "before 7" / "later" rows are visual stubs at the top/bottom for clipped events. Plan assumes this looks right at typical event density; if it gets crowded, the stub rows can be expanded. v1 ships at fixed dimensions and we tune from the first real runs.
- Reusing Type 3's calendar picker means either extracting it into a shared sub-component now or copy-and-adapting. Extraction is cleaner; copy is faster. Plan defaults to extraction with `<CalendarServicePicker>` shared by Types 3 and 9, falling back to copy-and-adapt if Type 3's form has too much typeId-coupling.
- Importance markers (`*Title*`) collide with markdown emphasis. The chronological event-list markdown rendering needs to escape or strip the asterisks before emitting the line. Same for the title shown inside the PNG box — use the cleaned title.
- The LLM-summary call needs a "complete_text"-style helper. The existing `judge_structured` is JSON-forcing and tuned for batch tagging; we should not reuse it here. Verify during implementation whether `llm_service` already has a plain-text helper; if not, add one.
- v1 does not pre-check Gmail attachment size limits (25MB) for the PNG. The PNG is small (<200KB typically), so this is theoretical, but worth noting.
- `context_text` is read by the LLM verbatim. If a user includes prompt-injection-shaped content there, the LLM will follow it. This is by design (it's the user's instructions) but worth being aware of.
- No backfill — existing workflows on Type 3 are not migrated. Users who want the new behavior create a new Type 9 workflow and decommission their Type 3 workflow at their own pace.
- Default config seeded with the type: `service="apple_calendar"`, `calendars=["Work","Family"]`, `days=7`, `context_text=""`, `reminder_patterns=[]`, `synonym_groups=[]`. Reasonable starting point even if the user has to swap calendars.

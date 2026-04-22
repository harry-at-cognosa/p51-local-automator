# Auto-Reply Email Workflows — How They Work

**Date:** 2026-04-22
**Scope:** The two new workflow types in the email category — `Auto-Reply (Draft Only)` (type_id 5) and `Auto-Reply (Approve Before Send)` (type_id 6).

---

## What happens when you create a workflow

`POST /workflows` with `{type_id, name, config}` → `backend/api/workflows.py:create_workflow` → inserts one row into `user_workflows`. That's it. **No runs yet, no MCP calls, no LLM calls.** The row stores:

- `type_id` (5 or 6, telling the dispatcher which runner to call later)
- `config` (your sender_filter, body_contains, signature, tone, etc. as JSON)
- `schedule` (null until you set one — more below)
- `enabled`, `deleted`, timestamps

Creation is pure bookkeeping. The expensive work only happens when a run is triggered.

## What happens at runtime

Both variants dispatch through the same entry point: `api/workflows.py:_run_workflow_background`, which switches on `type_id`:

```python
elif workflow.type_id == 5:
    await run_email_auto_reply_draft(...)
elif workflow.type_id == 6:
    await run_email_auto_reply_approve(...)
```

Both runners share most of their logic in `email_auto_reply_engine.py` via `find_and_generate_candidates()`. That function is what does the heavy lifting; each runner adds its own terminal step.

### Why only 2–3 steps show on the Run Detail page

I compressed four logical phases (list inbox → dedup → fetch-body-per-message → LLM-per-message) into a single `WorkflowSteps` row labeled "Fetch + filter + draft". Fine-grained steps are more useful for debugging and for demo narrative. Look at `email_monitor.py` for how the existing pattern splits phases cleanly. A future cleanup would split this into four distinct steps.

Here's what actually runs inside that one step today:

**Variant A — `email_auto_reply_draft.py`** (currently shows as 3 steps):

1. **Step 1 "Fetch + filter + draft"** — combines:
   - `mcp_client.mail_list_messages()` — list last N inbox messages
   - `_already_handled_ids()` — SELECT from `email_auto_reply_log` to skip anything acked
   - loop over candidates: `mail_get_message()` to pull full body, check sender_filter + body_contains, extract Reply-To header, call `llm_service.generate_email_reply()` for each match
2. **Step 2 "Save drafts to Mail.app"** — loops candidates; for each: `mail_save_draft()` (runs `osascript` subprocess that opens Mail.app and saves to Drafts), then inserts an `email_auto_reply_log` row (dedup marker)
3. **Step 3 "Write summary log"** — writes a plain-text artifact listing what was drafted

**Variant B — `email_auto_reply_approve.py`** (currently shows as 2 steps):

1. **Step 1 "Fetch + filter + draft"** — exact same engine call as Variant A
2. **Step 2 "Queue for approval"** — inserts rows into `pending_email_replies` with `status='pending'`, plus log rows with `action='queued_for_approval'`

### The dedup log is the source of truth for "already processed"

Every message that makes it past filtering gets exactly one row in `email_auto_reply_log` keyed on `(workflow_id, source_message_id)`. For Variant A that row is written as soon as the draft is saved. For Variant B it's written when the row is queued, and the `action` column gets updated to a terminal state (`approved_sent`, `edited_and_sent`, `saved_as_draft`, `rejected`) when you resolve it in the Pending Replies UI. So a message is never processed twice, regardless of which variant runs next.

### When you click "Approve & Send" in the UI

That's a separate code path — not part of the scheduled workflow run. `api/workflows.py:approve_pending_reply` → `mcp_client.mail_send_email()` (the MCP tool) → flips `pending_email_replies.status` + `email_auto_reply_log.action`. Same for Save as Draft (uses `mail_save_draft` via AppleScript) and Reject (DB-only, no Mail.app call).

## Scheduling — yes, both can be scheduled

Scheduling isn't type-specific. Any `user_workflows` row can have a `schedule` JSON like `{"type": "cron", "expr": "0 9 * * *"}` (9am daily) and APScheduler picks it up. The scheduler service is `backend/services/scheduler_service.py` — it scans `user_workflows` for enabled rows with non-null schedules on app startup and registers cron jobs. When a schedule fires, it calls the same `_run_workflow_background` dispatcher that the "Run Now" button does. Identical code path, different trigger string in the DB (`scheduled` instead of `manual`).

The UI may not yet have a friendly scheduler editor for these new types — the schedule field is there, it's just whatever the existing schedule UI exposes. Worth checking before the demo.

## Suggested cleanup — split into 4 fine-grained steps

A future edit would make Run Detail pages more useful for debugging and demo narrative:

| # | Step | What it does |
|---|---|---|
| 1 | List inbox | `mail_list_messages` (MCP) |
| 2 | Filter + dedup | apply sender/body rules, skip already-logged message IDs |
| 3 | Fetch bodies + generate replies | `mail_get_message` per candidate, LLM per candidate |
| 4 | Variant A: Save to Drafts / Variant B: Queue for approval | the terminal action |

Each step still fits in ~10 lines of runner code but shows distinctly on the Run Detail page with its own token count + timing.

## File map

- Dispatch: `backend/api/workflows.py` (look for `_run_workflow_background` and `WORKFLOW_RUNNERS`)
- Engine: `backend/services/workflows/email_auto_reply_engine.py`
- Variant A runner: `backend/services/workflows/email_auto_reply_draft.py`
- Variant B runner: `backend/services/workflows/email_auto_reply_approve.py`
- MCP + AppleScript helpers: `backend/services/mcp_client.py` (`mail_send_email`, `mail_save_draft`)
- LLM prompt: `backend/services/llm_service.py` (`generate_email_reply`)
- Tables: `backend/db/models.py` — `PendingEmailReplies`, `EmailAutoReplyLog`
- Approval queue API: `backend/api/workflows.py` bottom — list / approve / save-draft / reject
- Approval queue UI: `frontend/src/pages/PendingReplies.tsx` (route `/app/workflows/{id}/pending-replies`)
- Config form: `frontend/src/components/WorkflowConfigForm.tsx` (`typeId === 5 || typeId === 6` branch)

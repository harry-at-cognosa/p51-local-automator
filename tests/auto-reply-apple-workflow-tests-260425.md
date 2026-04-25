# Auto-Reply Workflow Tests

**Date:** 2026-04-25
**Scope:** Validate the two newest workflow types end-to-end:

- **Type 5** — `Auto-Reply (Draft Only)` (`short_name`: Draft Reply)
- **Type 6** — `Auto-Reply (Approve Before Send)` (`short_name`: Approve Reply)

Five scenarios + one safety check, covering both workflow types and both Mail.app accounts (iCloud and the Gmail account configured in Mail.app — `harry@cognosa.net`).

## A note on "Apple vs Google"

All six scenarios run through Apple Mail MCP today. "Gmail" tests here mean **a Gmail account configured in Mail.app**, accessed by the platform via Mail.app → IMAP → Gmail. There is no direct Gmail API path in p51 yet — that's the planned Google OAuth integration described in `docs/Gmail_email_access_controls_or_workspace_and_consumer_accounts_info.md`. So the only difference between an iCloud test and a Gmail test today is the `account` config field and which Drafts folder to inspect.

## Preconditions (verify before running any scenario)

1. **Backend running** on port 8001 (`python3 -m uvicorn backend.main:app --port 8001`).
2. **Mail.app open** with both `iCloud` and `harry@cognosa.net` accounts visible — needed for AppleScript draft saves and for the MCP `send_email` tool.
3. **At least one form-submission email** in `harry@cognosa.net` INBOX matching:
   - Sender contains `form-submission@squarespace.info`
   - Body contains `Sent via form submission from CogWrite Semantic Technologies`
4. **At least one Apple Card dispute notification email** in iCloud INBOX from `post.applecard.com`. These are the test pattern for scenarios 4–5. Each one identifiably contains both:
   - `Apple Card Customer:` (header line)
   - `Contact us to help resolve your dispute.` (body sentence)

   The platform's filter takes a single substring, so we'll use the more distinctive of the two (`Contact us to help resolve your dispute.`) as `body_contains`. The other string is just a visual confirmation that you're looking at the right email. Note: these are `noreply` emails — testing exists to verify draft generation and the account-selector behavior, **not** to send a real reply to Apple.
5. **Logged in** as admin in the browser at `http://localhost:8001/`.

## DB queries you'll use repeatedly

```sql
-- See pending replies for a workflow
SELECT pending_id, status, to_address, subject, source_message_id, resolved_at
FROM pending_email_replies WHERE workflow_id = <id> ORDER BY pending_id;

-- See the dedup log
SELECT log_id, source_message_id, action, created_at
FROM email_auto_reply_log WHERE workflow_id = <id> ORDER BY log_id;

-- Run history with step summaries
SELECT r.run_id, r.status, r.error_detail, s.step_number, s.step_name, s.output_summary
FROM workflow_runs r LEFT JOIN workflow_steps s ON s.run_id = r.run_id
WHERE r.workflow_id = <id> ORDER BY r.run_id DESC, s.step_number;
```

---

## Scenario 1 — Type 6 (Approve), Gmail, golden path: edit + send

**Goal:** Verify the queue, edit-in-place, and Edit & Send button send a real email through Mail.app.

**Setup:**
1. Workflows page → New Workflow → pick `Email — Approve Reply`.
2. Name: `S1 - Approve via Gmail`.
3. Config:
   - Account: `harry@cognosa.net`
   - Mailbox: `INBOX`
   - Sender filter: `form-submission@squarespace.info`
   - Body contains: `Sent via form submission from CogWrite Semantic Technologies`
   - Tone: `warm and professional`
   - Signature: your real signature (e.g. `Harry Layman\nCognosa`)
4. Save.

**Steps:**
1. On the workflow's detail page, click `Run Now`.
2. Wait until the run completes (Status: completed; should take 5–15s depending on LLM).
3. Click `Pending replies` (orange button — only appears for type 6).
4. Confirm one or more rows appear, each showing:
   - To: the form-submitter's email (their Reply-To, not `form-submission@squarespace.info`)
   - Subject: starts with `Re: `
   - Source: the original sender + subject in muted text
   - An editable body with the LLM-generated draft
5. Edit the body — change one sentence to confirm the edit is preserved.
6. Notice the button label changes to `Edit & Send` (because the body was modified).
7. Click `Edit & Send`.

**Expected:**
- Green success notice with `#<pending_id>: sent`.
- Row disappears from the queue (status flipped to `edited_and_sent`).
- A new outgoing message appears in `harry@cognosa.net` Sent Mail folder in Mail.app.
- The recipient (e.g. your test address) receives the email with your edited body.

**DB verification:**
```sql
SELECT status, user_action FROM pending_email_replies WHERE workflow_id=<id>;
-- expect: status='edited_and_sent', user_action='edited_and_sent'

SELECT action FROM email_auto_reply_log WHERE workflow_id=<id>;
-- expect: action='edited_and_sent'
```

---

## Scenario 2 — Type 6 (Approve), Gmail, dedup + reject

**Goal:** Verify (a) a previously-handled message does NOT reappear in a new run, and (b) Reject works without sending or saving anything.

**Setup:**
- Reuse the workflow from Scenario 1.
- Submit a NEW Squarespace form so a fresh form-submission email lands in the inbox.

**Steps:**
1. Click `Run Now` again on the same workflow.
2. Open `Pending replies`.
3. Confirm only the NEW message is there. The Scenario-1 message must NOT reappear.
4. Click `Reject` on the new pending row.

**Expected:**
- Green notice: `#<pending_id>: rejected`.
- Row disappears.
- No email sent. No draft created.

**DB verification:**
```sql
SELECT pending_id, status FROM pending_email_replies WHERE workflow_id=<id> ORDER BY pending_id;
-- expect: 2 rows total: one 'edited_and_sent' (S1), one 'rejected' (S2)

SELECT source_message_id, action FROM email_auto_reply_log WHERE workflow_id=<id>;
-- expect: 2 rows; both message IDs present, actions = 'edited_and_sent' and 'rejected'
```

5. Click `Run Now` once more (with no new form submission). Confirm the queue is empty — both prior messages are correctly skipped.

---

## Scenario 3 — Type 5 (Draft Only), Gmail

**Goal:** Verify drafts actually land in the Gmail account's Drafts folder via AppleScript.

**Setup:**
- Workflow #68 already exists (`CogWrite form ack (drafts)`, type 5, account `harry@cognosa.net`). Reuse it.
- Submit ONE more Squarespace form so there's an unhandled message available.

**Steps:**
1. Open workflow #68's detail page → `Run Now`.
2. Wait for completion.
3. Open the run's Details page. Verify it shows three steps:
   - Step 1: `Fetch + filter + draft` — output summary mentions N candidates, token count populated
   - Step 2: `Save drafts to Mail.app` — output summary "Saved N of N drafts"
   - Step 3: `Write summary log` — produces a `drafts_saved.txt` artifact

4. Open Mail.app → `harry@cognosa.net` account → Drafts folder.

**Expected:**
- One new draft per matched message.
- Each draft addressed to the form-submitter (Reply-To), with `Re: <original subject>`, body is the LLM-generated reply + signature.
- Sender is `harry@cognosa.net`.

**DB verification:**
```sql
SELECT action FROM email_auto_reply_log WHERE workflow_id=68 ORDER BY log_id DESC;
-- expect: most recent rows action='draft_saved'
```

5. Run again with no new form submissions. Verify zero drafts created the second time (dedup working). Step 1's output summary should say `0 candidates`.

---

## Scenario 4 — Type 5 (Draft Only), iCloud (Apple Card dispute emails)

**Goal:** Verify the same draft path works for iCloud — the account selector is honored, drafts land in the iCloud Drafts folder, sender is correct. Uses real Apple Card dispute notification emails as the source data so no synthetic test emails are needed.

**Setup:**
1. Confirm you have at least one unhandled Apple Card dispute notification in iCloud INBOX (sender ends `post.applecard.com`, body contains `Contact us to help resolve your dispute.`).
2. New Workflow → `Email — Draft Reply`.
3. Name: `S4 - Draft via iCloud (Apple Card)`.
4. Config:
   - Account: `iCloud`
   - Mailbox: `INBOX`
   - Sender filter: `post.applecard.com`
   - Body contains: `Contact us to help resolve your dispute.`
   - Signature: anything short
5. Save.

**Steps:**
1. Run Now.
2. Wait for completion.
3. Open Mail.app → iCloud → Drafts.

**Expected:**
- One new draft per matched message.
- Each draft addressed to the noreply address from the Apple Card sender (e.g. `noreply@post.applecard.com` or whatever's in the From / Reply-To header).
- The draft is in iCloud's Drafts folder, NOT Gmail's. (Critical — verifies `from_account` is honored in `mail_save_draft`.)
- Sender shown is iCloud.
- LLM-generated body is reasonable given the Apple Card content (will probably acknowledge the dispute notice in a generic-but-on-topic way).

**Don't actually send these drafts.** They go to a noreply address. The point is to verify the platform mechanics, not produce a real reply. Delete the drafts after inspection.

**DB verification:**
```sql
SELECT action, source_account FROM email_auto_reply_log WHERE workflow_id=<id>;
-- expect: action='draft_saved', source_account='iCloud'
```

---

## Scenario 5 — Type 6 (Approve), iCloud, Save as Draft path (Apple Card)

**Goal:** Verify the third action (Save as Draft) on the approval queue uses AppleScript to save into the right account's Drafts, without sending.

**Setup:**
1. Confirm there's an unhandled Apple Card dispute email in iCloud INBOX that hasn't already been processed by Scenario 4's workflow. (If Scenario 4 already drafted from your only candidate, submit a new dispute follow-up isn't realistic — just wait for the next Apple Card dispute notification, or run scenario 4 first against an older message and use a newer one here. The dedup log is per-workflow, so a different workflow_id will treat the same message as fresh.)
2. New Workflow → `Email — Approve Reply`.
3. Name: `S5 - Approve via iCloud (Apple Card)`.
4. Config:
   - Account: `iCloud`
   - Mailbox: `INBOX`
   - Sender filter: `post.applecard.com`
   - Body contains: `Contact us to help resolve your dispute.`
   - Signature: anything
5. Save.

**Steps:**
1. Run Now.
2. Open `Pending replies` for that workflow.
3. Edit the body slightly (so the platform records `final_body`).
4. Click `Save as Draft` (NOT Approve & Send).

**Expected:**
- Green notice: `#<pending_id>: saved_as_draft`.
- A new draft appears in iCloud Drafts (NOT Gmail Drafts), with the edited body and your signature appended.
- No outgoing email sent — Sent Mail unchanged.

**Important:** do NOT click `Approve & Send` here. The to_address is a noreply Apple address — sending would either bounce or vanish into Apple's noreply void, neither of which validates anything useful. Save as Draft is the action under test.

**DB verification:**
```sql
SELECT status, user_action, final_body IS NOT NULL AS body_was_edited
FROM pending_email_replies WHERE workflow_id=<id>;
-- expect: status='saved_as_draft', user_action='saved_as_draft', body_was_edited=true

SELECT action FROM email_auto_reply_log WHERE workflow_id=<id>;
-- expect: action='saved_as_draft'
```

---

## Scenario 6 (bonus, safety check) — Empty filters MUST not process anything

**Goal:** Confirm the engine refuses to acknowledge anything when both `sender_filter` and `body_contains` are empty. This is an important guardrail to prevent accidental inbox-wide replies.

**Setup:**
1. New Workflow → `Email — Draft Reply`.
2. Name: `S6 - Empty filters guard`.
3. Config:
   - Account: `iCloud` (or anything)
   - Sender filter: `(empty)`
   - Body contains: `(empty)`
4. Save.

**Steps:**
1. Run Now.
2. Open the run's Details.

**Expected:**
- Step 1 output summary: `Generated 0 reply draft(s) for acknowledgment.`
- Run completes successfully with NO drafts created and NO emails sent.

**Code reference:** the guard is in `email_auto_reply_engine.py:_matches_filters`:
```python
if not sender_filter and not body_contains:
    return False
```

**DB verification:**
```sql
SELECT COUNT(*) FROM email_auto_reply_log WHERE workflow_id=<id>;
-- expect: 0
```

If this scenario produces ANY drafts, that's a bug — file it before any further auto-reply work ships.

---

## Coverage matrix

| Scenario | Workflow Type | Account | Test data | Action exercised |
|---|---|---|---|---|
| 1 | Approve (6) | Gmail | Squarespace form submission | Edit & Send |
| 2 | Approve (6) | Gmail | Squarespace form submission | Reject + dedup |
| 3 | Draft Only (5) | Gmail | Squarespace form submission | Save to Drafts via AppleScript |
| 4 | Draft Only (5) | iCloud | Apple Card dispute notification | Account-selector honored |
| 5 | Approve (6) | iCloud | Apple Card dispute notification | Save as Draft from queue |
| 6 (bonus) | Draft Only (5) | iCloud | (none — empty-filter test) | Empty-filter safety guard |

- 2 scenarios per workflow type minimum: 5 covers 3, 6 covers 3 ✓
- 2 scenarios per account minimum: Gmail covers 3, iCloud covers 3 ✓

## Cleanup after testing

- Delete drafts created in Mail.app if you don't want them.
- Soft-delete the test workflows from the Workflows list page (red Delete button).
- Optional DB cleanup if you want a clean slate for further testing:
  ```sql
  -- WARNING: hard delete; only do this on dev. The platform's normal delete is soft.
  TRUNCATE TABLE email_auto_reply_log RESTART IDENTITY CASCADE;
  TRUNCATE TABLE pending_email_replies RESTART IDENTITY CASCADE;
  ```

## Known caveats

- **Mail.app must remain open** during runs that save drafts — AppleScript launches it if needed but it's faster if already running.
- **First LLM call may take 8–15 seconds**; subsequent calls in the same run are faster due to prompt caching.
- **Reply-To extraction** only works if the source email actually has a `Reply-To` header — otherwise it falls back to the `From` address. For Squarespace forms this is set to the submitter's email (great). For Apple Card dispute notifications it's typically a noreply address and the draft will be addressed there — fine for testing the platform mechanics, but those drafts should never actually be sent.
- **No iCloud-to-Gmail or vice-versa cross-account testing** — the account selected in config is also the sender. If your test email arrived in iCloud but you set the workflow to use `harry@cognosa.net`, the workflow will look in Gmail's INBOX, not iCloud's. Match account to where the test email lives.

# Type 5 and Type 6 Workflow Configuration Parameters

**Workflow types:** 5 (Auto-Reply Draft Only), 6 (Auto-Reply Approve Before Send)
**Shared engine:** `backend/services/workflows/email_auto_reply_engine.py`
**Date documented:** 2026-05-05

Both types use the same engine and read the same config fields. They differ only in their terminal action (type 5 saves to Mail.app Drafts; type 6 queues to `pending_email_replies` for human approval).

## Configuration fields

### `account`
Example: `"iCloud"`

Mail.app account name to operate on. Passed verbatim to every MCP call (list, fetch, save_draft, send). Determines which configured Mail.app account this workflow targets.

### `mailbox`
Example: `"INBOX"`

Mailbox within the account to read from. Passed to the message-list and message-fetch MCP calls.

### `period`
Example: `"last 7 days"`

**Not used by types 5 or 6.** It's in the seed defaults but the engine never reads it. The engine reads only `account`, `mailbox`, `sender_filter`, `body_contains`, `body_email_field`, `signature`, `tone`, `fetch_limit`. `period` is a leftover copy of type 1's config shape and should be removed from the seed defaults to avoid confusing users.

### `sender_filter`
Example: `"post.applecard.apple"`

Case-insensitive substring match against the message's `From` field. A pre-fetch optimization: messages whose preview sender doesn't match are skipped before the full message body is downloaded. If empty, no sender filtering.

### `body_contains`
Example: `"dispute investigation"`

Case-insensitive substring match against the message body (after the body is fetched). If empty, no body filtering.

### `body_email_field`
Example: `""` (empty) or `"Reply to:"`

A literal label to look for inside the body. When set and found, the engine extracts the email address that appears immediately after it (regex at `email_auto_reply_engine.py:235`). This handles senders that come from a no-reply address but bury the real contact in the body — Apple Card is the canonical example: the email arrives from `post.applecard.apple` but the body says "If you need to contact us, reply to: support@apple.com".

When empty, the engine falls back through this priority chain to find the reply target:
1. AppleScript reply-to lookup
2. MCP-exposed reply-to keys
3. The original `From` address

### `signature`
Example: `""` (empty)

Text appended to the LLM-generated reply body. Empty means no signature.

### `tone`
Example: `"warm and professional"`

Style instruction passed to the LLM via `generate_email_reply()`. The function uses it to shape the reply.

### `fetch_limit`
Example: `50`

Maximum number of recent inbox messages to pull in step 1. Tradeoff: higher catches more, costs more MCP time and token consumption; lower is faster but may miss matches if you have a busy inbox between scheduled runs.

## Substring matching semantics

Both `sender_filter` and `body_contains` use Python's raw `in` substring test (with both sides lowercased). There are **no word boundaries** — `"his"` will match `history`, `historic`, the standalone word `his`, and mid-word occurrences like `archist`. Likewise `"apple"` would match `pineapple@x.com`.

If word-boundary or anchored matching is needed later, that's a regex change (e.g., `\b` boundaries), but it is not the current behavior.

## Empty-filter safety guard

The engine refuses to run if BOTH `sender_filter` and `body_contains` are empty — that would match every recent message and draft a reply to all of them. The run terminates immediately without touching the inbox.

## Group-and-pick-the-winner behavior (no config field)

Beyond filtering, the engine groups matched messages by `to_address` and only drafts a reply for the **most recent** message in each group. The other (older) messages in the group are still recorded in `email_auto_reply_log` (tagged with the action taken on the group's winner) so they are not re-evaluated on the next run.

## Field summary table

| Field              | Used? | Default                 | Purpose                                                           |
|--------------------|-------|-------------------------|-------------------------------------------------------------------|
| `account`          | Yes   | (none — required)       | Mail.app account name                                             |
| `mailbox`          | Yes   | (none — required)       | Mailbox within the account                                        |
| `period`           | No    | `"last 7 days"`         | Ignored. Leftover from type 1 config; safe to remove.            |
| `sender_filter`    | Yes   | `""`                    | Substring match on `From`                                         |
| `body_contains`    | Yes   | `""`                    | Substring match on body                                           |
| `body_email_field` | Yes   | `""`                    | Label preceding a real reply address inside body text             |
| `signature`        | Yes   | `""`                    | Appended to LLM-drafted reply                                     |
| `tone`             | Yes   | `"warm and professional"` | Style hint to the LLM                                            |
| `fetch_limit`      | Yes   | `50`                    | Max recent inbox messages to pull                                 |

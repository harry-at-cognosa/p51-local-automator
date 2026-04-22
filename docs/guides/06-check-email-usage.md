# How to Use the /check-email Skill

## What It Does

`/check-email` reads emails from Apple Mail (locally, no cloud proxy), categorizes them by topic, flags urgent items, and generates an Excel report. The AI makes all judgment calls — topic assignment and urgency assessment — each time you run it.

## Basic Invocation

```
/check-email
```

With no arguments, it uses these defaults:
- **Account:** iCloud
- **Mailbox:** INBOX
- **Period:** Last 7 days
- **Topics:** Business & Finance, Technology & AI, Personal & Social, Marketing & Promotions, Government & Institutional

## Parameters

| Parameter | What it does | Default |
|-----------|-------------|---------|
| `--period` | How far back to look | "last 7 days" |
| `--topics` | Comma-separated category names | 5 default categories |
| `--account` | Which Mail.app account to search | iCloud |
| `--mailbox` | Which mailbox within the account | INBOX |

All parameters are optional and can be combined.

## Examples

### Change the time period

```
/check-email --period "last 24 hours"
/check-email --period "last 3 days"
/check-email --period "since April 1"
/check-email --period "last month"
/check-email --period "past 2 weeks"
```

Natural language works. The AI interprets the period and filters messages by date.

### Custom topics

```
/check-email --topics "Client Projects, Invoices & Billing, AI Tools, Newsletters, Junk"
```

The AI will sort every email into one of your specified topics (or "Other" if none fit). You are not limited to 5 — use as many or few as you want. Topic names are freeform; the AI interprets them based on the name alone.

```
/check-email --topics "Urgent Action Required, Can Wait, Ignore"
```

Topics can be action-oriented rather than content-based — the AI adapts.

```
/check-email --topics "From Clients, From Vendors, Internal, Newsletters, Unknown"
```

Topics can be sender-oriented. The AI uses sender domain and name to categorize.

### Different account

```
/check-email --account "harry@cognosa.net"
```

Searches the Gmail/Google Workspace account configured in Mail.app. Account names must match what Mail.app shows (use the account name or email address as it appears).

Available accounts on this machine:
- `iCloud` (harry.layman@icloud.com)
- `Exchange` (harry.layman@cogwrite.com — legacy)
- `harry@cognosa.net` (Google Workspace)

### Different mailbox

```
/check-email --account iCloud --mailbox "1-Newsletters"
/check-email --account iCloud --mailbox "241-invoices-receipts"
```

Any mailbox visible in Mail.app can be targeted. Use `list_mailboxes` to see all available mailboxes if unsure of the name.

### Combined parameters

```
/check-email --account "harry@cognosa.net" --period "last 3 days" --topics "Client Work, Billing, AI & Dev Tools, Other"
```

```
/check-email --period "since March 15" --topics "Tax Related, Financial, Everything Else" --account iCloud --mailbox "241-invoices-receipts"
```

### Natural language (no flags)

You can also just describe what you want in plain English after the command:

```
/check-email check my cognosa gmail for the last 2 weeks, categorize by client projects, internal, and newsletters
```

```
/check-email look at my iCloud inbox from this week and tell me what needs a response
```

The AI will interpret your intent and set parameters accordingly.

## How Topic Assignment Works

Topics are **not keyword-based**. The AI reads each email's sender, subject, and (when needed) body content, then uses judgment to assign a single topic. This means:

- An email from `quicken@mail.quicken.com` about "Online Backup" goes to "Technology & AI" or "Business & Finance" depending on your topic list — the AI picks the best fit
- An email with subject "Breaking news: A'ja Wilson signs record deal" goes to sports/personal, not "Business & Finance," even though "deal" is a financial word
- If your topics are "Urgent, Not Urgent" the AI assesses importance, not content category

**The same set of emails can produce different categorizations with different topic lists.** This is by design — the topics shape the AI's lens.

## How Urgency Assessment Works

Independent of topic assignment, each email is assessed for urgency. The AI flags an email as urgent if it:

- Has a **deadline** or **due date** (especially approaching ones)
- Requires a **response or action** (not just a notification)
- Involves **financial obligations** (invoices, payment requests, disputes)
- Contains **time-sensitive language** ("action required", "expires", "ASAP")
- Is from a **government agency** with a required action

Urgency is always assessed regardless of the topic list — even with custom topics, urgent items get flagged.

## Output

Every run creates a timestamped folder:

```
output/email_monitor_{YYYYMMDD_HHMMSS}/
  email_categorized.json    -- raw data (reusable by other tools)
  email_monitor_*.xlsx      -- formatted Excel workbook
```

The Excel workbook contains:
- **Summary sheet** — total counts, urgent count, topic breakdown table
- **All Emails sheet** — every email chronologically, with topic column, filterable
- **Per-topic sheets** — one sheet per topic with that topic's emails
- Urgent emails are **highlighted in red** across all sheets

## Tips

1. **Start broad, then narrow.** Run with defaults first to see what's in your inbox, then re-run with targeted topics if you want a different lens.

2. **Use for triage.** Topics like "Needs Response, FYI Only, Junk" turn the report into an action list.

3. **Combine with mailbox targeting.** If you've already sorted mail into mailboxes (like "241-invoices-receipts"), scanning a specific mailbox with relevant topics gives focused results.

4. **The JSON is reusable.** The `email_categorized.json` file can be consumed by other scripts or workflows — it's a clean, structured dataset of your email with AI-assigned metadata.

5. **Multiple runs are cheap.** Each run reads from local Mail.app (instant) and the AI categorizes inline (no separate API call). Re-running with different topics takes seconds.

## Limitations

- **Date filtering is approximate.** The skill fetches the most recent N messages and then filters by date. If your inbox has very high volume, older messages in the period may be missed. Increase the fetch limit by asking for it (e.g., "check last 30 days, get at least 200 messages").

- **Search is subject/sender only.** The `search_messages` tool searches subject lines and sender names, not full body text. For body-level filtering, the AI reads individual message content as needed.

- **One account per run.** You can't scan multiple accounts in a single invocation. Run the skill once per account if you want cross-account coverage.

- **Mail.app must be running.** The Apple Mail MCP communicates with Mail.app via AppleScript, so the app needs to be open (it can be in the background).

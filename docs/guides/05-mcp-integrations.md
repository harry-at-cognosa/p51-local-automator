# Learning Guide: MCP Integrations (Gmail, Calendar, Sheets)

## What Is MCP?

**Model Context Protocol (MCP)** is how Claude Code connects to external services. Instead of writing API client code yourself, you enable an MCP "connector" and Claude gets new tools it can call directly -- like `search_threads` for Gmail or `list_events` for Calendar.

Think of it this way:
- Without MCP: You write Python code using the Gmail API, handle OAuth tokens, parse responses
- With MCP: Claude calls `mcp__claude_ai_Gmail__search_threads` and gets structured results back

MCP connectors are managed by Anthropic and run through their proxy (`mcp-proxy.anthropic.com`).

## Setting Up Gmail MCP

### Step 1: Enable the Connector

1. Type `/mcp` in Claude Code CLI
2. Select **enable**
3. Choose **"claude.ai Gmail"** from the list
4. A browser window opens for Google OAuth
5. Sign in with your Google account and approve permissions
6. Return to the CLI

**Important:** If the CLI doesn't pick up the authentication, restart the Claude Code session. The auth is stored on the claude.ai account side and syncs on session start.

### Step 2: Verify Connection

Ask Claude to list your Gmail labels:
```
List my Gmail labels
```

If it works, you'll see your custom labels. System labels (INBOX, SENT, etc.) are always available.

## Available Gmail MCP Tools

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `search_threads` | Search for email threads | `query` (Gmail search syntax), `pageSize`, `pageToken` |
| `get_thread` | Read full thread content | `threadId`, `messageFormat` (MINIMAL or FULL_CONTENT) |
| `list_labels` | List custom labels | `pageSize` |
| `create_draft` | Compose a draft email | (message details) |
| `label_message` | Apply a label to a message | message ID, label ID |
| `list_drafts` | List draft emails | `pageSize` |

### Gmail Search Query Syntax

The `query` parameter uses the same syntax as Gmail's search bar:

```
newer_than:7d                          # Last 7 days
after:2026/04/01                       # After a specific date
before:2026/04/15                      # Before a specific date
from:someone@example.com              # From a specific sender
subject:invoice                        # Subject contains "invoice"
is:unread                              # Unread messages only
has:attachment                         # Has attachments
"exact phrase"                         # Exact phrase match
is:unread AND newer_than:3d            # Combine with AND/OR
```

### Pagination

`search_threads` returns at most 50 threads per call. If there are more:
- The response includes a `nextPageToken`
- Pass it as `pageToken` in the next call
- Repeat until no `nextPageToken` is returned

## How We Used It: Gmail Topic Monitor

### Architecture Decision: Claude as Agent

For the Gmail monitor, **Claude itself is the agent**, not a Python script. Why?

1. **MCP tools are only accessible through Claude** -- a standalone Python script can't call them
2. **Topic categorization benefits from LLM judgment** -- Claude understands that "Completed: Action needed" is NOT urgent because the snippet says "All parties have completed"
3. **Urgency detection is a judgment call** -- "action required" in a marketing email is different from "action required" for a deprecation notice

This is a fundamentally different architecture from Task 1 (data analyzer), where a Python script did all the work:

| | Task 1: Data Analyzer | Task 3: Gmail Monitor |
|--|----------------------|----------------------|
| Who does the thinking? | Python script (heuristics) | Claude (LLM judgment) |
| Who formats output? | Python script (openpyxl) | Python script (openpyxl) |
| Who orchestrates? | Claude runs script, presents results | Claude reads email, categorizes, calls script |
| MCP needed? | No (local files) | Yes (Gmail) |
| Could run without Claude? | Yes (fully standalone) | No (needs MCP + LLM judgment) |

### The Pipeline

```
Claude searches Gmail (MCP tool)
  -> Claude reads each thread's sender, subject, snippet
  -> Claude assigns topic + urgency using judgment
  -> Claude saves categorized data as JSON
  -> Claude calls Python script to generate Excel
  -> Claude presents summary to user
```

### What Made This "Agentic"

The key moment: two DocuSign emails had "Action needed" in the subject line, but Claude correctly marked them as NOT urgent because the snippet said "All parties have completed." A keyword-based system would have flagged both as urgent. Claude understood the *meaning*, not just the words.

## Personal vs. Workspace Gmail

Both work identically through MCP. The OAuth flow is the same -- you just sign in with whichever Google account you want. The only potential issue: Workspace admins can restrict third-party app access, which would block the OAuth. Personal Gmail has no such restrictions.

## Error Handling

The MCP proxy (`mcp-proxy.anthropic.com`) can have temporary outages (502 errors). During our testing we hit one. For the learning phase, just retry. For production (Phase 5), implement retry logic with 2-3 attempts and a graceful failure message.

Since Claude is the orchestrator, it can handle transient failures naturally -- retry, inform the user, try a different approach. This is an advantage over a rigid script that would simply crash on a 502.

## Google Calendar and Sheets MCP

These follow the same pattern as Gmail:
- Enable via `/mcp`
- Authenticate with Google OAuth
- Claude gets new tools (e.g., `list_events` for Calendar, `read_sheet` for Sheets)

We'll set these up when we build:
- **Task 4 (Event Extractor)** -- Calendar MCP for reading meeting invitations
- **Task 1 enhancement** -- Sheets MCP for reading/writing Google Sheets as a data source

## Gotchas & Lessons Learned

1. **Auth syncs on session start** -- If you authenticate but the CLI doesn't see the tools, restart the session.
2. **Search results are threads, not messages** -- A thread can contain multiple messages (replies). Use `get_thread` for full content.
3. **Snippets are truncated** -- The `snippet` field in search results is short. Use `get_thread` with `FULL_CONTENT` if you need the full email body.
4. **MCP proxy outages happen** -- Build retry logic for production use. For learning, just wait and retry.
5. **Rate limits** -- Don't fetch hundreds of threads in rapid succession. Batch reasonably (20-50 per call).

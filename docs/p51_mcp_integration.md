# p51-local-automator MCP Integration

## Overview

**File:** `backend/services/mcp_client.py` (281 lines)

MCP (Model Context Protocol) provides access to local applications like Apple Mail and Apple Calendar via standardized tool interfaces.

## MCP Server Definitions

| Server Name | NPM Package | Used By |
|-------------|-------------|---------|
| `apple-mail` | `@griches/apple-mail-mcp` | Types 1, 5, 6 |
| `apple-calendar` | `@griches/apple-calendar-mcp` | Type 3 |

### Invocation Pattern
Each MCP call spawns a new subprocess via `npx`:
```python
MCP_SERVERS = {
    "apple-mail": StdioServerParameters(
        command="npx",
        args=["@griches/apple-mail-mcp"],
    ),
    "apple-calendar": StdioServerParameters(
        command="npx",
        args=["@griches/apple-calendar-mcp"],
    ),
}
```

### Session Management
Each tool call opens a fresh MCP session:
```python
async with mcp_session("apple-mail") as session:
    result = await session.call_tool("list_messages", {...})
```

**Implications:**
- No session reuse between calls
- Each call spawns `npx` subprocess
- Latency: ~1-2 seconds per MCP call
- Parallel calls possible via asyncio

---

## Apple Mail MCP Tools

| Function | MCP Tool | Purpose | Used By |
|----------|----------|---------|---------|
| `mail_list_mailboxes()` | `list_mailboxes` | List all mailboxes | Utility |
| `mail_list_messages()` | `list_messages` | List recent messages | Types 1, 5, 6 |
| `mail_get_message()` | `get_message` | Get full message content | Types 5, 6 |
| `mail_search_messages()` | `search_messages` | Search by query | Utility |
| `mail_send_email()` | `send_email` | Send email | Type 6 (approve action) |

### Function Details

#### `mail_list_messages(account, mailbox, limit)`
```python
async def mail_list_messages(account: str, mailbox: str = "INBOX", limit: int = 50) -> list[dict]:
    content = await call_tool("apple-mail", "list_messages", {
        "account": account,
        "mailbox": mailbox,
        "limit": limit,
    })
    return json.loads(content[0].text) if content else []
```
**Returns:** `[{id, sender, subject, date, snippet}, ...]`

#### `mail_get_message(account, mailbox, message_id)`
```python
async def mail_get_message(account: str, mailbox: str, message_id: int) -> dict:
    content = await call_tool("apple-mail", "get_message", {...})
    return json.loads(content[0].text) if content else {}
```
**Returns:** `{content, sender, subject, ...}`
**Note:** `content` may be empty for HTML-only emails

#### `mail_send_email(to, subject, body, from_account)`
```python
async def mail_send_email(to: str, subject: str, body: str, from_account: str | None = None) -> dict:
    args = {"to": to, "subject": subject, "body": body}
    if from_account:
        args["from_account"] = from_account
    content = await call_tool("apple-mail", "send_email", args)
```

---

## AppleScript Fallbacks

The MCP server has gaps, so some operations use `osascript` directly:

| Function | Why AppleScript? | Used By |
|----------|-----------------|---------|
| `mail_get_message_source()` | MCP can't get HTML-only message bodies | Types 5, 6 |
| `mail_get_reply_to()` | MCP doesn't expose Reply-To header | Types 5, 6 |
| `mail_save_draft()` | MCP has no draft creation tool | Type 5 |

### AppleScript Pattern
```python
script = f'''
tell application "Mail"
    set theAccount to first account whose name is "{account}"
    set theMailbox to mailbox "{mailbox}" of theAccount
    set theMessage to (first message of theMailbox whose id is {message_id})
    return source of theMessage
end tell
'''
result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20)
```

### `mail_get_message_source(account, mailbox, message_id)`
**Why needed:** Mail.app's `content` scripting property returns empty for HTML-only messages. The raw source is always available.

```python
async def mail_get_message_source(account: str, mailbox: str, message_id: int) -> str | None:
    script = f'''
    tell application "Mail"
        try
            set theAccount to first account whose name is "{_applescript_escape(account)}"
            set theMailbox to mailbox "{_applescript_escape(mailbox)}" of theAccount
            set theMessage to (first message of theMailbox whose id is {int(message_id)})
            return source of theMessage
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
    result = await asyncio.to_thread(_run)
    return output if valid else None
```

### `mail_get_reply_to(account, mailbox, message_id)`
**Why needed:** MCP's `get_message` does NOT expose Reply-To header (verified empirically).

```python
async def mail_get_reply_to(account: str, mailbox: str, message_id: int) -> str | None:
    script = f'''
    tell application "Mail"
        try
            ...
            set rt to reply to of theMessage
            if rt is missing value then
                return ""
            end if
            return rt as string
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
```
**Returns:** Reply-To address string or None

### `mail_save_draft(to, subject, body, from_account)`
**Why needed:** MCP server has no draft creation tool.

```python
async def mail_save_draft(to: str, subject: str, body: str, from_account: str | None = None) -> dict:
    script = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{
            subject:"{_applescript_escape(subject)}",
            content:"{_applescript_escape(body)}",
            visible:false
        }}
        tell newMessage
            make new to recipient at end of to recipients with properties {{
                address:"{_applescript_escape(to)}"
            }}
        end tell
        {sender_line if from_account}
        save newMessage
        return "saved"
    end tell
    '''
```

---

## Apple Calendar MCP Tools

| Function | MCP Tool | Purpose | Used By |
|----------|----------|---------|---------|
| `calendar_list_events()` | `list_events` | List events in date range | Type 3 |
| `calendar_list_calendars()` | `list_calendars` | List all calendars | Utility |

### `calendar_list_events(calendar, from_date, to_date)`
```python
async def calendar_list_events(calendar: str, from_date: str, to_date: str) -> list[dict]:
    content = await call_tool("apple-calendar", "list_events", {
        "calendar": calendar,
        "from_date": from_date,
        "to_date": to_date,
    })
    return json.loads(content[0].text) if content else []
```
**Date format:** `"15 April 2026"` (human readable)
**Returns:** `[{startDate, endDate, summary, location, ...}, ...]`

---

## MCP vs AppleScript Usage Summary

| Operation | MCP Available? | Fallback Used? |
|-----------|---------------|----------------|
| List mailboxes | Yes | No |
| List messages | Yes | No |
| Get message | Yes | Yes (for HTML-only) |
| Get Reply-To | No | Yes |
| Get raw source | No | Yes |
| Save draft | No | Yes |
| Send email | Yes | No |
| List calendars | Yes | No |
| List events | Yes | No |

---

## Data Flow Example: Type 5 Auto-Reply

```
mail_list_messages(account, mailbox)
    -> Returns: [{id, sender, subject, date, snippet}, ...]
           |
           v
Filter by sender_filter, body_contains (in Python)
           |
           v
mail_get_message(account, mailbox, message_id)
    -> Returns: {content, sender, subject, ...}
    -> Problem: content empty for HTML-only emails
           |
           v (fallback if content empty)
mail_get_message_source(account, mailbox, message_id)
    -> Returns: Raw RFC822 source (via AppleScript)
    -> Parsed in Python to extract body
           |
           v
mail_get_reply_to(account, mailbox, message_id)
    -> Returns: Reply-To header (via AppleScript)
    -> Used to determine actual recipient
           |
           v
LLM generates reply
           |
           v
mail_save_draft(to, subject, body, from_account)
    -> Creates draft via AppleScript
    -> Saves to account's Drafts folder
```

---

## Key Insight

MCP provides basic operations, but Apple Mail's scripting limitations require AppleScript fallbacks for:
- HTML-only email bodies
- Reply-To header extraction
- Draft creation

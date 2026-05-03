# p51-local-automator Input Sources

## Summary Table

| Type ID | Type Name | Runtime Data Source | Configuration Source |
|---------|-----------|--------------------|--------------------|
| 1 | Email Topic Monitor | MCP: Apple Mail (mail_list_messages) | Config: account, mailbox, period, topics, scope |
| 2 | Transaction Data Analyzer | File: CSV or XLSX at file_path | Config: file_path, start_date, end_date, days |
| 3 | Calendar Digest | MCP: Apple Calendar (calendar_list_events) | Config: calendars, days |
| 4 | SQL Query Runner | Database: SQLAlchemy connection | Config: connection_string, query, query_name |
| 5 | Auto-Reply (Draft Only) | MCP: Apple Mail (list + get + reply-to) | Config: account, sender_filter, body_contains, tone, signature |
| 6 | Auto-Reply (Approve Before Send) | MCP: Apple Mail (same as Type 5) | Config: same as Type 5 |

---

## Type 1: Email Topic Monitor

### Runtime Data Source
- **Source:** MCP Apple Mail server
- **Tool:** `mail_list_messages(account, mailbox, limit=100)`
- **Returns:** JSON array of `{id, sender, subject, date, snippet}`

### Configuration (from `user_workflows.config`)
| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `account` | string | "iCloud" | Mail.app account name |
| `mailbox` | string | "INBOX" | Mailbox name |
| `period` | string | "last 7 days" | Time period filter |
| `topics` | array | [] (uses defaults) | Topic names for categorization |
| `scope` | string | "" | Focus area filter |

**Default Topics (when empty):**
- Business & Finance
- Technology & AI
- Personal & Social
- Marketing & Promotions
- Government & Institutional

---

## Type 2: Transaction Data Analyzer

### Runtime Data Source
- **Source:** Local filesystem
- **Format:** CSV or Excel (.xlsx, .xls)
- **Expected columns:** Date, Account, Payee, Category, Amount (auto-detected)

### Configuration (from `user_workflows.config`)
| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `file_path` | string | "" | **Required.** Path to CSV/Excel file |
| `start_date` | string | "" | Start date (YYYY-MM-DD) |
| `end_date` | string | "" | End date (YYYY-MM-DD) |
| `days` | integer | null | Days from start date |
| `key_fields` | array | [] | Override column detection |

---

## Type 3: Calendar Digest

### Runtime Data Source
- **Source:** MCP Apple Calendar server
- **Tool:** `calendar_list_events(calendar, from_date, to_date)` per calendar
- **Returns:** JSON array of events with startDate, endDate, summary, location

### Configuration (from `user_workflows.config`)
| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `calendars` | array | ["Work", "Family"] | Calendar names to fetch |
| `days` | integer | 7 | Lookahead window in days |
| `service` | string | "apple_calendar" | Calendar service (fixed) |

---

## Type 4: SQL Query Runner

### Runtime Data Source
- **Source:** External database via SQLAlchemy
- **Connection:** Synchronous connection (postgresql:// works, +asyncpg does NOT)
- **Execution:** `pandas.read_sql(text(query), conn)`

### Configuration (from `user_workflows.config`)
| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `connection_string` | string | "" | **Required.** SQLAlchemy URL |
| `query` | string | "" | **Required.** SQL query |
| `query_name` | string | "query" | Name for output files |

### Security Constraints (hardcoded)
- **Allowed:** `SELECT`, `WITH`, `EXPLAIN` only
- **Blocked:** `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE`

---

## Type 5: Auto-Reply (Draft Only)

### Runtime Data Source
- **Source:** MCP Apple Mail server + AppleScript fallbacks
- **Tools used:**
  - `mail_list_messages()` - list inbox
  - `mail_get_message()` - get message content
  - `mail_get_message_source()` - AppleScript fallback for HTML-only emails
  - `mail_get_reply_to()` - AppleScript to get Reply-To header

### Configuration (from `user_workflows.config`)
| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `account` | string | "iCloud" | **Required.** Sender account |
| `mailbox` | string | "INBOX" | Source mailbox |
| `sender_filter` | string | "" | **Required.** Substring to match in From |
| `body_contains` | string | "" | **Required.** Substring to match in body |
| `body_email_field` | string | "" | Label to extract email (e.g., "Email:") |
| `signature` | string | "" | Appended to LLM reply |
| `tone` | string | "warm and professional" | LLM tone directive |
| `fetch_limit` | integer | 50 | Max messages to scan |

### Safety Note
- Empty `sender_filter` blocks execution (prevents inbox nuke)

---

## Type 6: Auto-Reply (Approve Before Send)

### Runtime Data Source
- Same as Type 5

### Configuration
- Same as Type 5

### Output Destination
- `pending_email_replies` table (database)
- User approves via UI at `/app/workflows/{id}/pending-replies`

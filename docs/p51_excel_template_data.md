# p51-local-automator Excel Template Data

## For wrkfl_1-6.xlsx Empty Columns

This document contains the data to fill in the empty columns (`process_desc_steps`, `input_source`, `output_formats`) in the `docs/wrkfl_1-6.xlsx` template.

---

## Complete Row Data Table

| type_id | type_name | process_desc_steps | input_source | output_formats |
|---------|-----------|-------------------|--------------|----------------|
| 1 | Email Topic Monitor | 1. Fetch emails via MCP mail_list_messages() 2. Categorize with LLM (topic + urgency) 3. Generate Excel via subprocess email_to_excel.py | MCP: Apple Mail inbox; Config: account, mailbox, period, topics, scope | JSON (email_categorized.json), XLSX (email_monitor_{timestamp}.xlsx) |
| 2 | Transaction Data Analyzer | 1. Run analyze_data.py subprocess (profile, filter, charts, quality) 2. Analyze findings with LLM | File: CSV or XLSX; Config: file_path, date filters | MD (profile, summary, quality), XLSX (filtered data), PNG (charts), JSON (LLM analysis) |
| 3 | Calendar Digest | 1. Fetch events via MCP calendar_list_events() per calendar 2. Analyze with LLM (importance, conflicts, notes) | MCP: Apple Calendar; Config: calendars list, days | JSON (calendar_digest.json) |
| 4 | SQL Query Runner | 1. Execute SQL via SQLAlchemy + pandas 2. Analyze results with LLM | Database: Connection string + query from config | CSV, XLSX (query results), JSON (LLM analysis) |
| 5 | Auto-Reply (Draft Only) | 1. Fetch + filter + LLM draft via shared engine 2. Save drafts to Mail.app via AppleScript 3. Write summary log | MCP: Apple Mail inbox; Config: sender_filter, body_contains, tone, signature | Mail.app Drafts, TXT (summary), DB (email_auto_reply_log) |
| 6 | Auto-Reply (Approve Before Send) | 1. Fetch + filter + LLM draft via shared engine 2. Queue for approval in pending_email_replies table | MCP: Apple Mail inbox; Config: sender_filter, body_contains, tone, signature | DB (pending_email_replies, email_auto_reply_log) |

---

## Detailed process_desc_steps

### Type 1: Email Topic Monitor
```
Step 1: Fetch emails
- Call MCP mail_list_messages(account, mailbox, limit=100)
- Filter by date using parse_period() (e.g., "last 7 days" -> cutoff datetime)
- Build enriched list: id, sender, subject, date, snippet

Step 2: Categorize emails
- Call llm_service.categorize_emails() with topic list
- LLM returns: index, topic, urgent, urgency_reason per email
- Merge LLM results with email data
- Save to email_categorized.json

Step 3: Generate Excel report
- Subprocess: python3 scripts/email_to_excel.py input.json --output-dir
- Creates multi-sheet workbook: Summary, All Emails, per-topic sheets
- Urgent rows highlighted pink; color-coded topic sheets
```

### Type 2: Transaction Data Analyzer
```
Step 1: Analyze data (subprocess scripts/analyze_data.py)
  Internal sub-steps (not tracked by workflow engine):
  1a. Ingest & Profile: Load CSV/XLSX, auto-detect date/amount/category columns
  1b. Filter & Select: Date range filter, drop low-value columns
  1c. Analyze & Chart: Statistics, period comparison, matplotlib charts
  1d. Outlier Detection: 3-sigma outliers, missing values, duplicates

Step 2: Analyze findings
- Read step1_data_profile.md and step3_summary_report.md
- Call llm_service.judge_structured() with analysis prompt
- Save to step5_llm_analysis.json
```

### Type 3: Calendar Digest
```
Step 1: Fetch calendar events
- For each calendar in config list:
  - Call MCP calendar_list_events(calendar, from_date, to_date)
- Merge all events, sort chronologically

Step 2: Analyze events
- Format events for LLM: [index] startDate - endDate | summary | calendar | location
- Call llm_service.judge_structured() for importance/conflict/notes
- Merge LLM analysis with event data
- Save to calendar_digest.json
```

### Type 4: SQL Query Runner
```
Step 1: Execute SQL query
- Validate read-only: must match SELECT/WITH/EXPLAIN, no INSERT/UPDATE/DELETE etc.
- Create SQLAlchemy engine with connection_string
- Execute via pandas.read_sql()
- Save to {query_name}_results.csv and .xlsx

Step 2: Analyze results
- Send first 50 rows + df.describe() to LLM
- Call llm_service.judge_structured()
- Save to {query_name}_analysis.json
```

### Type 5: Auto-Reply (Draft Only)
```
Step 1: Fetch + filter + draft
- Call find_and_generate_candidates() shared engine:
  - mail_list_messages() -> filter by sender_filter, body_contains
  - Dedup via email_auto_reply_log table
  - mail_get_message() for body (with HTML fallback via mail_get_message_source)
  - Group by recipient, pick newest per group
  - LLM generate_email_reply() for winners only

Step 2: Save drafts to Mail.app
- For each candidate: mail_save_draft() via AppleScript
- Insert dedup rows to email_auto_reply_log (action='draft_saved')

Step 3: Write summary log
- Create drafts_saved.txt with full details of each draft
```

### Type 6: Auto-Reply (Approve Before Send)
```
Step 1: Fetch + filter + draft
- Same as Type 5 Step 1 (shared engine)

Step 2: Queue for approval
- Insert each candidate to pending_email_replies table (status='pending')
- Insert dedup rows to email_auto_reply_log (action='queued_for_approval')
- User reviews via UI at /app/workflows/{id}/pending-replies
```

---

## Detailed input_source

| Type | Runtime Data Source | Configuration Source |
|------|--------------------|--------------------|
| 1 | MCP: Apple Mail (mail_list_messages) | Config: account, mailbox, period, topics, scope |
| 2 | File: CSV or XLSX at file_path | Config: file_path, start_date, end_date, days |
| 3 | MCP: Apple Calendar (calendar_list_events) | Config: calendars, days |
| 4 | Database: SQLAlchemy connection | Config: connection_string, query, query_name |
| 5 | MCP: Apple Mail (list + get + reply-to) | Config: account, sender_filter, body_contains, tone, signature |
| 6 | MCP: Apple Mail (same as Type 5) | Config: same as Type 5 |

---

## Detailed output_formats

| Type | File Outputs | Database Outputs | Other Outputs |
|------|-------------|-----------------|--------------|
| 1 | JSON (categorized), XLSX (report) | workflow_artifacts | - |
| 2 | MD (3 reports), XLSX (data), PNG (2-3 charts), JSON (analysis) | workflow_artifacts | - |
| 3 | JSON (digest) | workflow_artifacts | - |
| 4 | CSV (results), XLSX (results), JSON (analysis) | workflow_artifacts | - |
| 5 | TXT (summary log) | email_auto_reply_log, workflow_artifacts | Mail.app Drafts folder |
| 6 | - | pending_email_replies, email_auto_reply_log | UI queue at /app/workflows/{id}/pending-replies |

---

## Compact Format for Excel Cells

### process_desc_steps (condensed)
| Type | Value |
|------|-------|
| 1 | 1. Fetch emails (MCP) 2. Categorize (LLM) 3. Generate Excel (subprocess) |
| 2 | 1. Analyze data (subprocess: profile/filter/charts/quality) 2. LLM analysis |
| 3 | 1. Fetch events (MCP per calendar) 2. Analyze (LLM: importance/conflicts) |
| 4 | 1. Execute SQL (read-only validated) 2. Analyze results (LLM) |
| 5 | 1. Fetch+filter+draft (shared engine) 2. Save drafts (AppleScript) 3. Write log |
| 6 | 1. Fetch+filter+draft (shared engine) 2. Queue for approval (DB) |

### input_source (condensed)
| Type | Value |
|------|-------|
| 1 | MCP Apple Mail; Config: account, period, topics |
| 2 | CSV/XLSX file; Config: file_path, date filters |
| 3 | MCP Apple Calendar; Config: calendars, days |
| 4 | Database; Config: connection_string, query |
| 5 | MCP Apple Mail; Config: filters, tone, signature |
| 6 | MCP Apple Mail; Config: filters, tone, signature |

### output_formats (condensed)
| Type | Value |
|------|-------|
| 1 | JSON + XLSX |
| 2 | MD + XLSX + PNG + JSON |
| 3 | JSON |
| 4 | CSV + XLSX + JSON |
| 5 | Mail.app Drafts + TXT + DB |
| 6 | DB only (pending_email_replies) |

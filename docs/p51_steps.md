# p51-local-automator Step Definitions

## Overview

All steps are **hardcoded in Python**. Users cannot change step count, names, or sequence.

## Step Count Summary

| Type ID | Type Name | Total Steps |
|---------|-----------|-------------|
| 1 | Email Topic Monitor | 3 |
| 2 | Transaction Data Analyzer | 2 |
| 3 | Calendar Digest | 2 |
| 4 | SQL Query Runner | 2 |
| 5 | Auto-Reply (Draft Only) | 3 |
| 6 | Auto-Reply (Approve Before Send) | 2 |

---

## Type 1: Email Topic Monitor

**File:** `backend/services/workflows/email_monitor.py`
**Total Steps:** 3 (hardcoded at line 88)

### Step 1: Fetch emails (lines 93-124)

**What it does:**
- Call MCP `mail_list_messages(account, mailbox, limit=100)`
- Filter by date using `parse_period()` (e.g., "last 7 days" -> cutoff datetime)
- Build enriched list: id, sender, subject, date, snippet

**Configurable:** Period, account, mailbox from config

### Step 2: Categorize emails (lines 127-169)

**What it does:**
- Call `llm_service.categorize_emails()` with topic list
- LLM returns: index, topic, urgent, urgency_reason per email
- Merge LLM results with email data
- Save to `email_categorized.json`

**Configurable:** Topics, scope from config

### Step 3: Generate Excel report (lines 172-196)

**What it does:**
- Subprocess: `python3 scripts/email_to_excel.py input.json --output-dir`
- Creates multi-sheet workbook: Summary, All Emails, per-topic sheets
- Urgent rows highlighted pink; color-coded topic sheets

**Configurable:** None - script is fixed

**Step Definition Quality:** Well-defined. Clear boundaries, single responsibility per step.

---

## Type 2: Transaction Data Analyzer

**File:** `backend/services/workflows/data_analyzer.py`
**Total Steps:** 2 (hardcoded at line 68)

### Step 1: Analyze data (lines 73-102)

**What it does:**
Runs subprocess `scripts/analyze_data.py` (120s timeout) which has internal sub-steps:

1. **Ingest & Profile:** Load CSV/XLSX, auto-detect date/amount/category columns
2. **Filter & Select:** Date range filter, drop low-value columns
3. **Analyze & Chart:** Statistics, period comparison, matplotlib charts
4. **Outlier Detection:** 3-sigma outliers, missing values, duplicates

**Configurable:** File path, date filters from config

### Step 2: Analyze findings (lines 105-135)

**What it does:**
- Read `step1_data_profile.md` and `step3_summary_report.md`
- Call `llm_service.judge_structured()` with analysis prompt
- Save to `step5_llm_analysis.json`

**Configurable:** None - LLM prompt is fixed

**Step Definition Quality:** Coarse-grained. Step 1 does 4 internal operations but exposes them as one step.

---

## Type 3: Calendar Digest

**File:** `backend/services/workflows/calendar_digest.py`
**Total Steps:** 2 (hardcoded at line 43)

### Step 1: Fetch calendar events (lines 48-73)

**What it does:**
- For each calendar in config list:
  - Call MCP `calendar_list_events(calendar, from_date, to_date)`
- Merge all events, sort chronologically

**Configurable:** Calendars list, days from config

### Step 2: Analyze events (lines 76-160)

**What it does:**
- Format events for LLM: `[index] startDate - endDate | summary | calendar | location`
- Call `llm_service.judge_structured()` for importance/conflict/notes
- Merge LLM analysis with event data
- Save to `calendar_digest.json`

**Configurable:** None - LLM prompt is fixed

**Step Definition Quality:** Well-defined. Clean separation of data fetch vs analysis.

---

## Type 4: SQL Query Runner

**File:** `backend/services/workflows/sql_runner.py`
**Total Steps:** 2 (hardcoded at line 63)

### Step 1: Execute SQL query (lines 68-85)

**What it does:**
- Validate read-only: must match `SELECT/WITH/EXPLAIN`, no `INSERT/UPDATE/DELETE` etc.
- Create SQLAlchemy engine with connection_string
- Execute via `pandas.read_sql()`
- Save to `{query_name}_results.csv` and `.xlsx`

**Security validation (lines 33-39):**
- Must match: `^\s*(SELECT|WITH|EXPLAIN)\b`
- Must NOT contain: `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE`

**Configurable:** Query and connection from config

### Step 2: Analyze results (lines 88-134)

**What it does:**
- Send first 50 rows + `df.describe()` to LLM
- Call `llm_service.judge_structured()`
- Save to `{query_name}_analysis.json`

**Configurable:** None - LLM prompt is fixed

**Step Definition Quality:** Well-defined. Security validation is clear.

---

## Type 5: Auto-Reply (Draft Only)

**File:** `backend/services/workflows/email_auto_reply_draft.py`
**Total Steps:** 3 (hardcoded at line 23)

### Step 1: Fetch + filter + draft (lines 31-41)

**What it does (via shared engine `find_and_generate_candidates()`):**
- `mail_list_messages()` -> filter by sender_filter, body_contains
- Dedup via `email_auto_reply_log` table
- `mail_get_message()` for body (with HTML fallback via `mail_get_message_source`)
- Group by recipient, pick newest per group
- LLM `generate_email_reply()` for winners only

**Configurable:** Filters, tone, signature from config

### Step 2: Save drafts to Mail.app (lines 48-98)

**What it does:**
- For each candidate: `mail_save_draft()` via AppleScript
- Insert dedup rows to `email_auto_reply_log` (action='draft_saved')

**Configurable:** Account from config

### Step 3: Write summary log (lines 101-139)

**What it does:**
- Create `drafts_saved.txt` with full details of each draft

**Configurable:** None - format is fixed

**Step Definition Quality:** Step 1 is coarse-grained - it actually does: list inbox -> filter -> dedup -> fetch bodies -> group by recipient -> LLM per winner. The shared engine hides this complexity.

---

## Type 6: Auto-Reply (Approve Before Send)

**File:** `backend/services/workflows/email_auto_reply_approve.py`
**Total Steps:** 2 (hardcoded at line 33)

### Step 1: Fetch + filter + draft (lines 40-50)

**What it does:**
- Same as Type 5 Step 1 (shared engine)

**Configurable:** Same config as Type 5

### Step 2: Queue for approval (lines 57-106)

**What it does:**
- Insert each candidate to `pending_email_replies` table (status='pending')
- Insert dedup rows to `email_auto_reply_log` (action='queued_for_approval')
- User reviews via UI at `/app/workflows/{id}/pending-replies`

**Configurable:** None - schema is fixed

**Step Definition Quality:** Same as Type 5 for step 1. Step 2 is pure database insert with dedup tracking.

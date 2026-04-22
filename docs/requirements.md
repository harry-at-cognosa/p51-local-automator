# Requirements: Simple Agentic Automation Demo Platform

## Overview

A set of practical office automations built as Claude Code native artifacts (skills, agents, scheduled triggers) to demonstrate agentic AI capabilities to front-line employees and managers at small companies. Each task is designed to be useful in a real workplace while showcasing specific Claude Code features.

---

## Task 1: Transaction Data Analyzer

### Purpose
Analyze transaction data from various sources, generate a filtered Excel report with key fields, produce a summary with charts, and flag outliers or data quality issues.

### Input Sources (any of)
- Google Sheet via user's Google Workspace account
- Excel file (.xlsx) in user's designated input folder
- CSV file in user's designated input folder

### Date Range Queries
- Start date + end date (triggers prior-period comparison)
- Start date + number of days (triggers prior-period comparison)
- "After" a certain date (no prior-period comparison)
- "Before" a certain date (no prior-period comparison)

### Output Artifacts
All stored in user's designated output folder and available for download.

**a) Filtered Excel File**
- Transactions within the specified date range
- "Key" fields only -- the agent should evaluate which columns are important and exclude columns that never change or are unlikely to be useful (e.g., if 25 columns exist but only 10-12 are meaningful)
- Clear formatting, headers, date sorting

**b) Summary Report**
- Characterize the data in the period (totals, averages, distributions by category)
- 1-2 charts illustrating useful patterns (e.g., spend by category, trend over time)
- Prior-period comparison where applicable (same-length period immediately before the requested range)
- Narrative summary of findings

**c) Data Quality Flags**
- Outlier transactions (unusually large/small amounts, unusual categories)
- Partial or incomplete records (missing required fields)
- Bad data (invalid dates, negative amounts where unexpected, duplicates)

### Configuration
- User's Google account (for Sheets source)
- Root input file location
- Root output file location
- Optional: preferred key fields override

---

## Task 2: SQL Query Runner & Analyzer

### Purpose
Execute read-only SQL queries against user-defined databases on an ad-hoc or scheduled basis, store results, and generate analysis with charts.

### Inputs
- Database connection (defined in user config by name)
- SQL query (typed ad-hoc or selected from saved queries)
- Schedule expression (optional, for recurring reports)

### Output Artifacts
- Query result dataset (stored as CSV/Excel)
- Analysis report with summary statistics
- Charts visualizing the query results
- All artifacts stored in user's output folder

### Constraints
- Read-only queries (SELECT) only -- no INSERT/UPDATE/DELETE
- Connection strings stored securely in user config, never logged

### Configuration
- Named database connections with connection strings
- Saved query library (name, SQL, description)
- Schedule expressions for recurring queries

---

## Task 3: Gmail Topic Monitor

### Purpose
Monitor selected Gmail accounts, categorize emails by user-defined topics, and produce organized reports highlighting urgent items.

### Inputs
- Gmail account(s) to monitor (1-2 accounts, one may be a Workspace account)
- Topic definitions with keywords
- Time period: last 24 hours (default for scheduled runs) or specified date range (ad-hoc)
- Output format: Google Sheet, Excel file, or both

### Output Artifacts
- Chronological list of emails organized by topic
- Each entry includes: sender, subject, date/time, snippet, topic classification
- Urgent/time-sensitive emails highlighted (visual formatting)
- Stored in designated output path and/or written to a Google Sheet

### Scheduling
- Default: runs daily for the past 24 hours when enabled
- Also available on-demand for any specified time period

### Configuration
- Gmail account(s) to monitor
- Topic list with keyword definitions
- Output format preference (Sheet, Excel, or both)
- Output path
- Schedule (default: daily at 8am, configurable)

---

## Task 4: Meeting/Event Extractor

### Purpose
Scan email for meeting invitations and calendar events, produce a formatted report with event details for a specified date range.

### Inputs
- Email account(s) to scan
- Date range for events
- On-demand execution

### Output Artifacts
- Formatted report (Excel + markdown) listing:
  - Event name/subject
  - Date and time
  - Sponsor/organizer
  - Other invitees
  - Location (if specified)
  - Summary/agenda (if available)
  - Accept/decline status
- Sorted chronologically

### Configuration
- Email account(s)
- Default date range (e.g., next 7 days)
- Output path

---

## Cross-Cutting Requirement: Multi-Step Workflows

A key demonstration goal is showing how agentic automations work as **multi-step pipelines** that are resilient, inspectable, and optionally interactive.

### Workflow Concepts

**Pipeline with Checkpointing:**
Each step in a multi-step automation saves its output artifacts before the next step begins. If step 3 of 5 fails, the user still has the outputs from steps 1 and 2. No work is lost.

**Human-in-the-Loop (Async Approval):**
For workflows where judgment matters, the pipeline can pause after a step and wait for user review. The user can:
- **Approve** and continue to the next step
- **Modify parameters** and re-run the current step with different settings
- **Skip** a step and proceed to the next one
- **Stop** the workflow entirely

**Workflow as the Client Deliverable:**
In practice, what clients want is for an expert to set up workflows that chain agents and skills together to produce analysis, reports, email replies, or alerts. The individual tasks (1-4) are building blocks; the real value is composing them into workflows tailored to a client's business process.

### Example: 5-Step Sales Analysis Workflow

To illustrate, here's how Tasks 1 and 2 might compose into a workflow:

1. **Ingest** -- Read transaction data from source (CSV/Excel/Sheet), validate, save cleaned dataset
2. **Analyze** -- Run date filtering, key field selection, generate summary stats. *Output: filtered Excel + stats report.* **[Checkpoint -- user reviews]**
3. **Compare** -- Pull prior-period data, compute comparisons, generate comparison charts. *Output: comparison report.* **[Optional approval gate]**
4. **Flag** -- Run outlier detection, data quality checks. *Output: quality report with flagged items.*
5. **Distribute** -- Email the reports to stakeholders, write summary to a shared Sheet, or alert a Slack channel about flagged items.

Each step's artifacts are saved in `output/workflow_{run_id}/step_{n}/` so the full trail is always available.

### Workflow State

A workflow run has:
- `run_id` -- unique identifier
- `status` -- running | paused_for_review | completed | failed
- `current_step` -- which step is active
- `step_results[]` -- output paths and status for each completed step
- `parameters` -- the config/parameters used (can be modified between steps)

This state is persisted as a YAML or JSON file in the output directory, so it survives interruptions.

---

## Test Data

Real-world test data is available at `/Users/harry/5_sample_agentic_apps/test_data/`:

| File | Rows | Description |
|------|------|-------------|
| household_trans_2016-2026_18338rows.csv | 18,338 | Personal financial transactions (Date, Account, Payee, Category, Amount) 2016-2026 |
| Quicken_data_3_...xlsx | 18,347 | Same Quicken data in Excel format with 7 columns |
| 1_retail_sales_amzn_nocats_5482_rows.xlsx | 5,482 | Amazon retail orders, 26 columns, product/pricing/shipping detail |
| 2_retail_sales_amzn_cats_3531_rows.xlsx | 5,415 | Amazon retail orders, categorized variant |
| AO1_ad_spend_daata_by_channel_v40207b.xlsx | 1,822 | Weekly ad spend & revenue by marketing channel, 2022-2024 |
| AO1_all_sales_data_by_channel_250207.xlsx | 280 | Weekly sales summary by channel, 2022-2024 |
| AO1_sales_data_v40207b.xlsx | 280 | Weekly sales summary (alternate version) |

Prefer using this real data over generating synthetic data. Generate additional data only when needed to test specific scenarios not covered.

---

## Future: Google Workspace Integration

Plan to set up a Google CLI interface token for the user's Workspace to enable:
- Reading and writing Google Sheets
- Creating charts and other outputs with Google products
- Writing to shared Workspace Google Drive folders
- This will be set up when we reach the MCP integration phase (Phase 3+)

---

## Cross-Cutting Requirements

### Per-User Configuration
- Each user has a YAML config file specifying all their data sources, paths, accounts, topics, and schedules
- In single-user mode: one config file on disk
- In future multi-user mode: configs in database, editable via web UI

### Artifact Storage
- All generated files stored in user's designated output folder
- Naming convention: `{task}_{date}_{descriptor}.{ext}`
- Available for local access and (future) download via web UI

### Data Sources
- Google Sheets (via Google Workspace MCP)
- Local Excel files (.xlsx)
- Local CSV files
- SQL databases (read-only)
- Gmail (via Gmail MCP)
- Google Calendar (via Calendar MCP)

---

## Future Tasks (Not Yet Specified in Detail)

5. Document Summarizer -- summarize PDFs/Word docs dropped in input folder
6. Expense Report Preparer -- draft expense reports from receipts/transactions
7. Weekly Status Report Generator -- aggregate data from multiple sources
8. Slack/Teams Channel Monitor -- categorize chat messages by topic

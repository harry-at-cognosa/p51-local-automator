# p51-local-automator Workflow Overview

## Summary

The p51-local-automator platform has **4 workflow categories** containing **6 workflow types**.

## Four Workflow Categories

| Category ID | Category Name | Label | Sort Order |
|-------------|---------------|-------|------------|
| 1 | email | Email | 10 |
| 2 | calendar | Calendar | 20 |
| 3 | analysis | Data Set Analysis | 30 |
| 4 | query | Structured Queries | 40 |

## Six Workflow Types

| Type ID | Category | Type Name | Short Name | Description |
|---------|----------|-----------|------------|-------------|
| 1 | Email | Email Topic Monitor | Topic Monitor | Fetch emails from Apple Mail or Gmail, categorize by topic with AI, assess urgency, and generate an Excel report. |
| 2 | Analysis | Transaction Data Analyzer | Transactions | Read transaction data from CSV/Excel, profile and filter by date, generate summary report with charts and outlier detection. |
| 3 | Calendar | Calendar Digest | Digest | Extract calendar events, detect conflicts, assess importance, and produce a formatted digest with optional Excel report. |
| 4 | Queries | SQL Query Runner | SQL Runner | Execute read-only SQL queries against configured databases, analyze results with AI, and generate charts and narrative. |
| 5 | Email | Auto-Reply (Draft Only) | Draft Reply | Scan inbox for matching emails, generate an acknowledgment reply with AI, and save it to the account's Drafts folder. No email is sent automatically. |
| 6 | Email | Auto-Reply (Approve Before Send) | Approve Reply | Scan inbox for matching emails, generate an acknowledgment reply with AI, and queue it in the app for human approval. User can approve, edit and send, save as draft, or reject each reply. |

## Architecture Overview

### Two-Layer Step System

1. **Workflow Engine** (`backend/services/workflow_engine.py`):
   - Generic step lifecycle management
   - Functions: `create_run()`, `start_step()`, `complete_step()`, `fail_step()`
   - Tracks: step_number, step_name, status, output_summary, llm_tokens_used
   - No knowledge of what each step does—purely bookkeeping

2. **Type-Specific Runner** (`backend/services/workflows/{type}.py`):
   - Defines the actual step count (passed to `create_run(total_steps=N)`)
   - Names each step (passed to `start_step(step_name="...")`)
   - Implements the step logic between `start_step()` and `complete_step()`
   - Decides what artifacts to generate and record

### Key Files

| Purpose | File Path |
|---------|-----------|
| Workflow engine | `backend/services/workflow_engine.py` |
| Type 1 runner | `backend/services/workflows/email_monitor.py` |
| Type 2 runner | `backend/services/workflows/data_analyzer.py` |
| Type 3 runner | `backend/services/workflows/calendar_digest.py` |
| Type 4 runner | `backend/services/workflows/sql_runner.py` |
| Type 5 runner | `backend/services/workflows/email_auto_reply_draft.py` |
| Type 6 runner | `backend/services/workflows/email_auto_reply_approve.py` |
| Shared email engine | `backend/services/workflows/email_auto_reply_engine.py` |
| Data analysis script | `scripts/analyze_data.py` |
| Email Excel script | `scripts/email_to_excel.py` |
| LLM service | `backend/services/llm_service.py` |
| MCP client | `backend/services/mcp_client.py` |

### Key Insight

**Steps are NOT defined in configuration.** The number of steps, their names, and their sequence are **hardcoded in Python** for each workflow type.

This is a **fixed workflow architecture** with **configurable inputs**, not a **workflow builder** where users define their own step sequences.

## Configuration vs Hardcoded Matrix

| Element | Where Defined | Modifiable by User? |
|---------|--------------|---------------------|
| Step count per type | Python (`create_run(total_steps=N)`) | No |
| Step names | Python (`start_step(step_name="...")`) | No |
| Step sequence | Python (code order) | No |
| LLM prompts | Python (hardcoded strings) | No |
| LLM model selection | Python (`llm_service.py`) | No |
| Output file formats | Python (hardcoded extensions) | No |
| Output file naming | Python (hardcoded patterns) | No |
| Email account/mailbox | Config JSON | Yes |
| Date period/filters | Config JSON | Yes |
| Topic lists | Config JSON | Yes |
| SQL query | Config JSON | Yes |
| File path for analysis | Config JSON | Yes |
| Sender/body filters | Config JSON | Yes |
| Tone/signature | Config JSON | Yes |

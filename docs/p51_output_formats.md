# p51-local-automator Output Formats

## Summary Table

| Type ID | Type Name | File Outputs | Database Outputs | Other Outputs |
|---------|-----------|-------------|-----------------|--------------|
| 1 | Email Topic Monitor | JSON, XLSX | workflow_artifacts | - |
| 2 | Transaction Data Analyzer | MD (3), XLSX, PNG (2-3), JSON | workflow_artifacts | - |
| 3 | Calendar Digest | JSON | workflow_artifacts | - |
| 4 | SQL Query Runner | CSV, XLSX, JSON | workflow_artifacts | - |
| 5 | Auto-Reply (Draft Only) | TXT | email_auto_reply_log, workflow_artifacts | Mail.app Drafts |
| 6 | Auto-Reply (Approve Before Send) | - | pending_email_replies, email_auto_reply_log | UI queue |

## Format Flexibility

| Type | Input Format | Output Format | User Can Change Output? |
|------|--------------|---------------|------------------------|
| 1 | Config JSON | JSON + XLSX | No - schema hardcoded |
| 2 | CSV/XLSX file | XLSX + PNG + MD + JSON | Columns from input; templates fixed |
| 3 | Config JSON | JSON | No - schema hardcoded |
| 4 | SQL query | CSV + XLSX + JSON | Columns from query; analysis schema fixed |
| 5 | Config JSON | Mail.app + text | No - text format hardcoded |
| 6 | Config JSON | Database rows | No - schema hardcoded |

---

## Type 1: Email Topic Monitor

### Output Files
| File | Format | Description |
|------|--------|-------------|
| `email_categorized.json` | JSON | Categorized email data |
| `email_monitor_{timestamp}.xlsx` | XLSX | Multi-sheet Excel report |

### JSON Schema (fixed in `email_monitor.py:144-153`)
```json
[{
  "topic": "string",
  "sender": "string",
  "subject": "string",
  "date": "string",
  "snippet": "string",
  "thread_id": "string",
  "urgent": boolean,
  "urgency_reason": "string"
}]
```

### Excel Structure (fixed in `email_to_excel.py`)
- **Sheet 1: "Summary"** - title, totals, topic table
- **Sheet 2: "All Emails"** - chronological list with auto-filter
- **Sheets 3+:** One sheet per topic, color-coded
- **Columns:** Date, Topic, Sender, Subject, Snippet, Urgent, Urgency Reason
- **Styling:** Urgent rows pink with red text

---

## Type 2: Transaction Data Analyzer

### Output Files
| File | Format | Description |
|------|--------|-------------|
| `step1_data_profile.md` | Markdown | Column summary, data types, statistics |
| `step2_filtered_data.xlsx` | XLSX | Filtered transaction data |
| `step3_summary_report.md` | Markdown | Analysis summary with tables |
| `step3_chart_by_category.png` | PNG | Horizontal bar chart (top 12) |
| `step3_chart_trend.png` | PNG | Time series with dual axis |
| `step3_chart_comparison.png` | PNG | Prior vs current period (if applicable) |
| `step4_quality_report.md` | Markdown | Outliers, missing values, issues |
| `step5_llm_analysis.json` | JSON | LLM narrative analysis |

### LLM Output Schema (fixed in `data_analyzer.py:32-37`)
```json
{
  "summary": "string",
  "findings": ["string", ...],
  "anomalies": ["string", ...],
  "suggested_charts": ["string", ...]
}
```

---

## Type 3: Calendar Digest

### Output Files
| File | Format | Description |
|------|--------|-------------|
| `calendar_digest.json` | JSON | Calendar analysis data |

### JSON Schema (fixed in `calendar_digest.py:141-149`)
```json
{
  "period": "string",
  "calendars": ["string", ...],
  "total_events": number,
  "summary": "string",
  "conflicts": [
    {"event_a": number, "event_b": number, "description": "string"}
  ],
  "urgent_items": ["string", ...],
  "events": [{
    "date": "string",
    "end_date": "string",
    "summary": "string",
    "calendar": "string",
    "location": "string",
    "importance": "high|normal|low",
    "conflict": boolean,
    "notes": "string"
  }]
}
```

---

## Type 4: SQL Query Runner

### Output Files
| File | Format | Description |
|------|--------|-------------|
| `{query_name}_results.csv` | CSV | Raw query results |
| `{query_name}_results.xlsx` | XLSX | Query results formatted |
| `{query_name}_analysis.json` | JSON | LLM analysis |

### LLM Output Schema (fixed in `sql_runner.py:101-107`)
```json
{
  "summary": "string",
  "findings": ["string", ...],
  "anomalies": ["string", ...],
  "suggested_charts": ["string", ...]
}
```

---

## Type 5: Auto-Reply (Draft Only)

### Output Files
| File | Format | Description |
|------|--------|-------------|
| `drafts_saved.txt` | Plain text | Summary log of drafts |

### Text Log Format (fixed in `email_auto_reply_draft.py:107-137`)
```
Auto-Reply (Draft Only) - run #{run_id}
Workflow: #{workflow_id}  {name}
Account: {from_account}
Saved: {saved} / {total}

========================================================================
Draft 1 of N
  To:               {to_address}
  Subject:          {reply_subject}
  Source from:      {source_from}
  Source subject:   {source_subject}
  Winner msg id:    {source_message_id}
  Covered msg ids:  {additional_handled_message_ids}
  LLM tokens:       {llm_tokens}

  Source body (first 400 chars):
    | {body preview}

  Generated reply body:
    | {reply text}
```

### Database Output
- **Table:** `email_auto_reply_log`
- **Action:** `draft_saved`

### Other Output
- **Mail.app Drafts folder:** Draft emails saved via AppleScript

---

## Type 6: Auto-Reply (Approve Before Send)

### Output Files
None - all output goes to database

### Database Output
- **Table:** `pending_email_replies` - queued replies with status='pending'
- **Table:** `email_auto_reply_log` - action='queued_for_approval'

### UI Output
- User reviews at `/app/workflows/{id}/pending-replies`
- Actions: Approve, Edit & Send, Save as Draft, Reject

---

## Key Insight

Output **content** varies based on input data, but output **structure** (JSON schemas, file formats, column layouts) is entirely defined in Python code. Users cannot customize output formats through configuration.

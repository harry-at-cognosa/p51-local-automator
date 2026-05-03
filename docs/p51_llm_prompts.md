# p51-local-automator LLM Prompts

## Overview

All LLM calls go through `backend/services/llm_service.py`:
- **Model:** claude-sonnet-4-20250514 (hardcoded default)
- **Max tokens:** 4096 (hardcoded default)
- **Caching:** Prompt caching enabled for system prompts
- **Output format:** All prompts require JSON-only responses

## Central LLM Function

**`judge_structured()` (lines 25-68):**
```python
def judge_structured(system, user_prompt, model="claude-sonnet-4-20250514", max_tokens=4096):
    # Makes API call with cache_control on system prompt
    # Strips markdown code fences from response
    # Parses JSON; returns {"result": parsed_json, "usage": token_counts}
```

## Prompt Customizability Summary

| Type | Prompt Aspect | User Configurable? |
|------|--------------|-------------------|
| 1 | Topic list | Yes (config) |
| 1 | Scope filter | Yes (config) |
| 1 | Urgency criteria | No |
| 1 | Output schema | No |
| 2 | Entire prompt | No |
| 3 | Importance values | No |
| 3 | Conflict detection | No |
| 4 | Analysis focus | No |
| 5-6 | Tone directive | Yes (config) |
| 5-6 | Signature | Yes (config) |
| 5-6 | Reply length rules | No |
| 5-6 | Greeting rules | No |
| All | Model selection | No (hardcoded) |
| All | Max tokens | No (hardcoded 4096) |
| All | Temperature | No (uses API default) |

---

## Type 1: Email Categorization Prompt

**Function:** `categorize_emails()` in `llm_service.py:71-118`

### System Prompt (hardcoded)
```
You are an email categorization assistant. You will receive a batch of emails
and must categorize each one into exactly ONE of the following topics:

{topic_list from config}
- Other (if none fit well)

{optional scope filter if configured}

For each email, also assess urgency:
- urgent: true if the email requires action, has a deadline, involves financial
  obligations, or is time-sensitive
- urgent: false for newsletters, notifications, marketing, and informational emails
- If urgent, provide a brief urgency_reason

Return a JSON array where each element has:
{"index": <0-based index>, "topic": "<topic name>", "urgent": <true/false>,
 "urgency_reason": "<reason or empty string>"}

Return ONLY the JSON array, no other text.
```

### User Prompt Format
```
Categorize these {N} emails:

[0] From: {sender} | Subject: {subject} | Date: {date} | Snippet: {snippet[:200]}
[1] From: {sender} | Subject: {subject} | Date: {date} | Snippet: {snippet[:200]}
...
```

### Configurable Elements
- Topic list (from config)
- Scope filter (from config)

### Hardcoded Elements
- Urgency criteria
- Output schema
- Categorization rules

---

## Type 2: Transaction Analysis Prompt

**Location:** `data_analyzer.py:28-39`

### System Prompt (hardcoded)
```
You are a data analysis assistant. You will receive a data
profile and a statistical summary produced by an automated transaction analyzer.

Provide a brief narrative analysis. Return JSON with these keys:
{
    "summary": "1-2 sentence overview of what the data shows",
    "findings": ["bulleted finding 1", "bulleted finding 2", ...],
    "anomalies": ["notable outlier or data quality issue 1", ...],
    "suggested_charts": ["chart type: brief description", ...]
}

Return ONLY the JSON, no other text.
```

### User Prompt Format
```
## Data Profile

{contents of step1_data_profile.md}

## Analysis Summary

{contents of step3_summary_report.md}
```

### Configurable Elements
None

### Hardcoded Elements
- Entire prompt
- Output schema

---

## Type 3: Calendar Analysis Prompt

**Location:** `calendar_digest.py:88-109`

### System Prompt (hardcoded)
```
You are a calendar analysis assistant. You will receive a list of calendar events.
For each event, assess:
1. importance: "high", "normal", or "low"
2. conflict: true if it overlaps with another event in the list
3. notes: brief prep notes (e.g. "bring insurance card", "allow travel time",
   "deadline day")

Also provide an overall summary at the top.

Return JSON with this structure:
{
    "summary": "Overview paragraph of the week ahead",
    "events": [
        {"index": 0, "importance": "high", "conflict": false, "notes": "..."},
        ...
    ],
    "conflicts": [
        {"event_a": 0, "event_b": 1, "description": "Both at 8am Thursday"}
    ],
    "urgent_items": ["Event summary that needs attention", ...]
}

Return ONLY the JSON, no other text.
```

### User Prompt Format
```
Analyze these {N} calendar events for the next {days} days:

[0] {startDate} - {endDate} | {summary} | Calendar: {calendar} | Location: {location}
[1] {startDate} - {endDate} | {summary} | Calendar: {calendar} | Location: {location}
...
```

### Configurable Elements
None

### Hardcoded Elements
- Importance values (high/normal/low)
- Conflict detection logic
- Notes generation rules

---

## Type 4: SQL Results Analysis Prompt

**Location:** `sql_runner.py:94-109`

### System Prompt (hardcoded)
```
You are a data analysis assistant. You will receive SQL query results.
Provide a brief analysis including:
1. Summary of what the data shows
2. Key patterns or trends
3. Any notable outliers or anomalies
4. Suggested visualizations

Return JSON:
{
    "summary": "Brief overview",
    "findings": ["finding 1", "finding 2", ...],
    "anomalies": ["anomaly 1", ...],
    "suggested_charts": ["chart type: description", ...]
}

Return ONLY the JSON, no other text.
```

### User Prompt Format
```
Query: {sql_query}

Results: {rows} rows, {cols} columns
Columns: {column_names}

Statistics:
{df.describe() output}

Sample data (first 50 rows):
{df.head(50).to_string()}
```

### Configurable Elements
None

### Hardcoded Elements
- Entire prompt
- Analysis focus

---

## Types 5 & 6: Email Reply Generation Prompt

**Function:** `generate_email_reply()` in `llm_service.py:121-187`

### System Prompt (hardcoded, with config injection)
```
You write short, genuine acknowledgment replies to inbound emails.
Your goal: confirm receipt, reassure the sender their message was seen,
set a reasonable expectation for follow-up, and stay brief.

Critical context - the reply will be SENT TO the address provided as
`To (reply destination)`. That address is the ground truth for who you
are writing to. Names appearing in the message body may refer to OTHER
parties and must NOT be used to address the reply unless you can confirm
the name belongs to the To address.

Hard rules:
- 2-4 sentences, no more.
- Never promise a specific time commitment you can't keep; use phrases
  like 'soon' or 'within a few days'.
- Don't invent facts not in the source message.
- Address by first name ONLY if a name in the body clearly belongs to
  the To address; otherwise use a generic greeting.
- Do NOT include a signature or sign-off block at the end.
- Tone: {tone from config}.

Return ONLY a JSON object:
{"subject": "Re: <original subject>", "body": "<reply text>"}
```

### User Prompt Format
```
Inbound email:
From: {source_from}
Subject: {source_subject}
To (reply destination): {to_address}
Body:
{source_body[:4000]}

{optional signature block to append}
```

### Configurable Elements
- `tone` (e.g., "warm and professional")
- `signature` (appended to reply)

### Hardcoded Elements
- Reply length rules (2-4 sentences)
- Greeting rules
- Time commitment rules
- Signature handling

---

## Key Insight

LLM prompts have minimal configurability. Users can adjust:
- Topic lists and scope (Type 1)
- Tone and signature (Types 5-6)

Everything else - response format, analysis criteria, behavioral rules - is hardcoded in Python.

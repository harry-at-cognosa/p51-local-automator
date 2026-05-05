# Location of LLM prompts by workflow type

**Date documented:** 2026-05-05

This document inventories where each workflow type's LLM prompt(s) live in the codebase. The pattern is currently mixed: some prompts are embedded in specialized helpers in `llm_service.py`, others are defined at the workflow-module level, and some are inline inside the workflow's run function.

## Conventions to know

`llm_service.py` exposes two kinds of entry points:

- **Specialized helpers** that own a specific prompt internally and present a use-case-shaped function signature (e.g., `categorize_emails(emails, topics, scope)`).
- **A generic helper** `judge_structured(system_prompt, user_prompt)` that takes any pair of prompts and returns a parsed JSON result. The prompts are owned by the caller.

Workflows that need a one-off prompt use `judge_structured` and define their prompt locally. Workflows whose prompt is reusable across calls have a specialized helper.

## Per-type inventory

### Type 1 — Email Topic Monitor (`email_monitor.py`)

- **Prompt location:** `backend/services/llm_service.py`, inside `categorize_emails()`.
- **Call site:** `email_monitor.py:129` — `llm_service.categorize_emails(enriched, topics, scope=scope)`.
- **Pattern:** specialized helper. The system and user prompts are constructed inside `categorize_emails()` from the supplied topics and scope.

### Type 2 — Transaction Data Analyzer (`data_analyzer.py`)

- **Prompt location:** `data_analyzer.py:28-39`, module-level constant `LLM_SYSTEM_PROMPT`.
- **User prompt:** built inline in the run function (`data_analyzer.py:115-121`) by concatenating the script's profile and summary markdowns.
- **Call site:** `data_analyzer.py:123` — `llm_service.judge_structured(LLM_SYSTEM_PROMPT, user_prompt)`.
- **Pattern:** workflow-owned constant + generic helper.

### Type 3 — Calendar Digest (`calendar_digest.py`)

- **Prompt location:** inline inside `run_calendar_digest()` at `calendar_digest.py:88-109` as a local `system = """..."""` string.
- **User prompt:** built inline immediately below the system string.
- **Call site:** `calendar_digest.py:113` — `llm_service.judge_structured(system, user_prompt)`.
- **Pattern:** workflow-owned, function-local + generic helper.

### Type 4 — SQL Query Runner (`sql_runner.py`)

- **Prompt location:** inline inside the run function at `sql_runner.py:94` as a local `system = """..."""` string.
- **User prompt:** built inline at `sql_runner.py:111`.
- **Call site:** `sql_runner.py:122` — `llm_service.judge_structured(system, user_prompt)`.
- **Pattern:** workflow-owned, function-local + generic helper (same as type 3).

### Types 5 and 6 — Email Auto-Reply (Draft / Approve Before Send)

Both types share the underlying engine `email_auto_reply_engine.py`, which is what makes the LLM call.

- **Prompt location:** `backend/services/llm_service.py`, inside `generate_email_reply()`.
- **Call site:** `email_auto_reply_engine.py:465` — `llm_service.generate_email_reply(...)`.
- **Pattern:** specialized helper. System and user prompts are constructed inside `generate_email_reply()` from the inbound message context, tone, signature, and other parameters.

## Summary table

| Type | Workflow                | Prompt location                                           | LLM helper                |
|------|-------------------------|-----------------------------------------------------------|---------------------------|
| 1    | Email Topic Monitor     | `llm_service.py` → `categorize_emails()`                  | specialized               |
| 2    | Transaction Data Analyzer | `data_analyzer.py` module-level `LLM_SYSTEM_PROMPT`     | `judge_structured`        |
| 3    | Calendar Digest         | `calendar_digest.py` inline (function-local)              | `judge_structured`        |
| 4    | SQL Query Runner        | `sql_runner.py` inline (function-local)                   | `judge_structured`        |
| 5    | Auto-Reply (Draft)      | `llm_service.py` → `generate_email_reply()`               | specialized               |
| 6    | Auto-Reply (Approve)    | `llm_service.py` → `generate_email_reply()` (shared)      | specialized               |

## Architectural notes

1. **No central prompt registry.** Prompts are wherever they were placed when each type was implemented. Auditing every prompt requires opening five different modules.
2. **`llm_service.py` is not the single source of truth.** It contains type-1 and types-5/6 prompts but not the others. The name suggests "all LLM behavior lives here" but only ~half does.
3. **Three of the five workflows** (types 2, 3, 4) own their prompts locally. This is fine when a prompt is genuinely use-case-specific; it's a problem if and when prompts need to be tunable from outside (e.g., per-group prompt overrides, prompt versioning, prompt A/B testing) — those features would require touching each workflow module.
4. **Future consideration.** Consolidating prompts into a registry — or at least into per-type prompt modules with a consistent naming convention — would simplify future work like prompt-tuning UIs, audit/log of prompt versions used per run, or automated prompt evaluation.

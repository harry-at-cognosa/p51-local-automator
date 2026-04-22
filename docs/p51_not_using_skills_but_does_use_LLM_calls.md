# p51 Architecture: No Skills (Today), Yes LLM Calls — and an Honest Correction

**Date:** 2026-04-22
**Purpose:** Clarify what the platform currently does with Claude, what it doesn't, *why* the initial choices were made, and — importantly — correct an overstatement made in chat about where agent orchestration does or doesn't belong.

---

## What the platform does today

All 6 workflow types (Email Topic Monitor, Transaction Data Analyzer, Calendar Digest, SQL Query Runner, Auto-Reply Draft, Auto-Reply Approve) follow the same pattern:

1. A Python function in `backend/services/workflows/*.py` is the **runtime orchestrator**.
2. That function calls MCP tools directly (`mail_list_messages`, `mail_get_message`, `calendar_list_events`, etc.) via `backend/services/mcp_client.py`.
3. When a specific judgment is needed — categorize these emails by topic, generate a reply body, assess event importance — the function calls `backend/services/llm_service.py` which makes **one prompt / one response** via the Anthropic SDK.
4. Results land in `workflow_runs`, `workflow_steps`, `workflow_artifacts`, plus workflow-specific tables like `pending_email_replies`.

Claude Code skills (`.claude/skills/*/SKILL.md`) are **not used anywhere** in this runtime. Neither is Claude Code as an orchestrator. Neither are multi-turn agent sessions with tool use.

The Anthropic SDK appears only for single-turn structured judgment calls inside `llm_service.py`.

## Why the initial 4 types were built this way

The first four workflow types are all variations on **deterministic ETL pipelines**:
- Fetch a batch of data from a known source
- Classify / filter / summarize each item
- Produce a known output shape (Excel, JSON, a digest)

For that shape of problem, a Python function doing the orchestration has genuine advantages:
- Cost: dozens of tokens of judgment per item, not an entire agent transcript per item
- Latency: no conversational turns, no tool-use round-trips
- Auditability: every step writes a well-defined `workflow_steps` row
- Testability: you can pytest the pipeline shape in seconds

So the decision for those four types wasn't "agents bad, Python good in general." It was "these four specific tasks are ETL pipelines and ETL pipelines are easier as Python."

The two auto-reply types (5 and 6) *also* inherited this pattern, which is fine for the form-submission-ack use case but starts to strain when the reply requires genuine reasoning about what to say — and that's where the story gets more interesting.

## Correction: agent orchestration IS production-grade at scale

In our chat I wrote this:

> Testability — you can pytest a Python function; you can't easily unit-test "did Claude interpret the skill correctly"
> Multi-tenancy — a web platform with 15 concurrent users needs a real backend to serve requests, not a CLI session per user

Both points contain a kernel of truth but overstate the case. The honest picture:

- **Agent orchestration is used in production at serious scale today.** Customer support platforms (Sierra, Decagon, Ada), sales/BD research tools, coding agents (including Claude Code itself, and the broader Claude Agent SDK ecosystem), and internal enterprise agents at large companies are all agent-orchestrated. Anthropic's own tool-use patterns ship in production for enterprise customers.
- **"CLI session per user" was a misleading mental model.** Production agent apps don't spawn a terminal session; they call the Claude API with tools defined, handle the multi-turn tool-use loop programmatically (often server-side), stream results, and persist whatever needs to be audited. The "CLI" was only ever the developer ergonomics of Claude Code for local work. For a web platform, agents show up as server-side loops that the backend drives, not as one-shot prompts.
- **Testability is harder with agents but not intractable.** You use eval harnesses with golden input/output sets, trace every tool call, snapshot state after each turn, and alert on drift. That's more work than `assert function(x) == y`, but it's a real discipline with well-understood tooling.
- **Multi-tenancy doesn't rule out agents.** You spin up an agent per request, not per user — 15 users each triggering a workflow that happens to be agent-orchestrated is the same operational shape as 15 users each hitting a REST endpoint.

Where **Python orchestration still wins**:
- High-throughput, well-shaped tasks (classify 10,000 emails a night)
- Strict cost ceilings per operation
- Regulated / audit-heavy environments where the bounded state machine matters more than flexibility
- Tasks where the "right next step" is genuinely known in advance

Where **agent orchestration wins**:
- Open-ended tasks where the right next step depends on what the previous step found
- User-extensible surfaces where non-programmers author behavior
- Reasoning-dense tasks (research, negotiation support, complex triage)
- Any task where an `if/else` tree would grow past maintainability

It is NOT a binary — the best platforms run **both patterns side by side**, picking the one that fits the task shape.

## Harry's original vision was right

The stated goal was to build an automator where users — not Python programmers — can extend the capabilities of the platform. That vision requires at least *some* agent-orchestrated workflow types, because skills are the natural artifact non-programmers produce.

The CLI-era work in `51_project_simple_agentic_automation.archive/` was exactly this pattern: three SKILL.md files (`check-email`, `list-events`, `analyze-data`) that any literate user could copy and modify. That was the right instinct; we just translated those three skills into Python runners because we needed a web platform as quickly as possible and Python was faster to ship.

## A path that supports both patterns

The current data model already accommodates this without a rewrite:
- `workflow_categories` — we already have Email, Calendar, Analysis, Queries
- `workflow_types` — currently 6 Python-backed types
- Nothing prevents adding a **new category or a set of types that are agent-orchestrated instead of Python-orchestrated**

A realistic next chapter:

### Add an "Agent Skill" workflow type

- Introduce `workflow_types` rows where the Python runner is a thin wrapper that spawns a Claude agent session with:
  - A system prompt and task spec (either hardcoded per type, or — for user-extensibility — stored as a `SKILL.md`-style field on the row)
  - A tool catalog exposing MCP calls, file writes, DB reads, etc. (scoped by group)
  - Resource caps (max turns, max tokens, max wall time, max tools calls)
  - Persistence hooks so every turn writes to `workflow_steps` + artifacts
- Each run = one agent session, server-side, recorded turn-by-turn

### Add user-editable skills later

- New UI: a SKILL editor where a manager writes markdown describing the task
- New `user_skills` table holding those per-user / per-group
- A workflow type "Run Skill" that takes a `skill_id` and runs it

### Keep deterministic types Python-orchestrated

- Email monitor, calendar digest, SQL runner, data analyzer — these stay as-is. They're ETL, not agent work.
- Auto-reply-draft stays Python. Auto-reply-approve could benefit from being agent-orchestrated later if the reply logic needs to branch on what the message actually says.

## The short version

- Today the platform has zero agent orchestration and zero skills. It uses the Anthropic SDK for single-turn LLM judgment calls inside Python orchestrators. That's a fine fit for the 6 types shipped so far.
- My earlier claim that this is inherently "the right answer" was too strong. Agents are production-grade; they just solve a different shape of problem than ETL pipelines.
- Your vision — user-extensible skills — **requires** at least one agent-orchestrated type. That's a clean next chapter, not a contradiction with what's shipped.
- Both patterns coexist naturally in the existing data model.

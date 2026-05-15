# Future use cases for the Agent-User Interaction (AG-UI) protocol

**Captured:** 2026-05-15
**Status:** evaluation only — no implementation planned at this time.

## Context

The question that prompted this memo: should p51 adopt the AG-UI
(Agent-User Interaction) protocol? The decision got tangled up with
two other architectural questions:

1. How users customize workflow behavior (forms-as-prompts today vs
   user-supplied skill files in the future).
2. Where the agent runs (local Mac, central server, or some
   sync'd-hybrid) — and whether that lets us escape the Apple Mail
   single-tenant constraint.

Recommendation up front: **mostly ignore AG-UI for now**; it addresses
a problem we don't have. The other two questions are real and worth
working through, but AG-UI isn't the lever for either of them.

## What AG-UI actually is (terse)

- **Wire protocol between a UI and an agentic backend.** Event-based
  over HTTP/WebSockets. Standardizes things like "agent emitted a
  thinking chunk," "agent called this tool," "agent wants a human
  decision."
- **Transport-agnostic on where the agent runs.** It's about the
  socket between UI and agent, not which machine the agent lives on.
- **Sister protocol to MCP, not competing.** MCP = agent ↔ tools, AG-UI
  = agent ↔ user, A2A = agent ↔ agent. Three layers.
- **Integrates with frameworks** (LangGraph, CrewAI, Pydantic AI,
  Mastra, etc.) — we use none of these; we have a custom
  `AgenticEngine` (`backend/services/agentic_engine.py`), so AG-UI
  would mean us writing the integration ourselves.
- **Custom-tools concept:** AG-UI's "frontend tool calls" let the UI
  render a tool the agent invokes (e.g., open a form mid-run). That's
  the closest AG-UI gets to "user-customizable workflows" — but it's
  about UI-side tools, not user-supplied agent skills.

Source: https://docs.ag-ui.com/introduction

## Untangling the three concerns

### A. User-customizable workflows

The current Type 7 (AWF-1) form-as-prompt model is genuinely flexible:

- `backend/services/agentic_engine.py:610-693` — `analysis_goal`,
  `processing_steps`, `report_structure`, `voice_and_style` flow as
  *free-text prompt fragments* into the agent's system+context block.
  Users have substantial control today; they're just writing English
  rather than code.
- Type 2 (`backend/services/workflows/data_analyzer.py:73-160`) is the
  shallower variant: config fields drive a deterministic script, and
  only the script's output gets LLM commentary.

The skill registry (`backend/services/skills/registry.py:67-97`) is
deliberately static, decorator-registered, and code-defined. There is
no dynamic-load mechanism today.

**Three escalation paths**, ranked by risk:

| Step | What it gives users | Risk to shared server |
|---|---|---|
| 1. Library of named "recipes" (curated `config` JSON presets users pick + tweak) | Faster onboarding, no real new flexibility | Zero — just more JSON |
| 2. User-defined named skill bundles: { system-prompt fragment + tool subset whitelist + config defaults } | Substantial behavior shaping without code | Low — no code execution; the LLM still runs |
| 3. User-supplied skill *code files* loaded into the registry at runtime | Arbitrary new tools the LLM can call | High — code execution on the shared server; sandboxing required (subprocess + seccomp/firejail, or per-user worker, etc.) |

AG-UI isn't on this ladder. AG-UI doesn't make user-supplied skill
code safer or harder; it doesn't change the customization surface at
all. **If user customization is the goal, work on this ladder
directly.** Recommendation: do step 2 next when we reach for it — get
most of the perceived flexibility of step 3 without the
sandbox/security burden.

### B. Where the agent runs (and the Apple Mail constraint)

The Apple Mail constraint is hard: Apple Mail MCP (`mcp_client.py:22-48`)
spawns a stdio subprocess that talks to `Mail.app` on the *same Mac*.
There's no remote transport for `@griches/apple-mail-mcp` — it has to
be co-resident with the user's Mail data.

The "local agent uses a remote headless agent on a server, keeping
state in sync" pattern isn't really a thing in the AG-UI sense. The
closest real architectures are:

1. **Thin local client, server-side agent.** Browser/native UI runs
   on the user's Mac, the agent loop + LLM call run on a central
   server. This is what we already do for everything except Apple
   Mail. AG-UI would standardize the wire here, but our current
   "poll workflow_runs every 2s" UI works.

2. **Remote agent + local sidecar for OS-locked services.** The
   agent runs centrally; per-user Apple Mail access is provided by a
   *small bridge daemon* on each user's Mac that exposes their local
   Apple Mail MCP over an *authenticated remote MCP transport*
   (MCP's spec supports SSE/HTTP transports, not just stdio). Server
   connects to bridge per-user on demand. **This is the architecture
   that would let us support Apple Mail across many users on a
   shared server**, and it's an *MCP* solution, not an AG-UI one.

3. **Local agent, local LLM call.** Everything runs on the user's
   Mac. No server multi-tenancy at all. Doesn't fit our "Mac Mini
   server for <15 users" framing.

The intuition about "local + remote in sync" is closest to #2 — which
is real, but the protocol that solves it is *remote MCP transport*,
not AG-UI. If/when multi-user Apple Mail support becomes a priority,
the engineering work is: (a) build the bridge daemon
(`apple-mail-mcp` already runs stdio; wrap it in an HTTP/SSE
listener), (b) change `mcp_client.mcp_session` to support a URL-based
connection per user, (c) authenticate the bridge to the server (mTLS
or a shared secret).

### C. The actual case for AG-UI in our codebase

AG-UI would buy us real value in three specific places:

1. **Streaming Type 7 progress.** AWF-1 takes ~4 minutes and the UI
   shows a step counter that polls. AG-UI's event stream
   (`thinking`, `tool_use`, `tool_result`, `step_complete`) would let
   us push detailed live progress — what stage the engine is in,
   what tool it just called, what the audit critique flagged. **We
   can build this without AG-UI** (hand-roll an SSE endpoint reading
   the same events `agentic_engine._run_agent_loop` already logs),
   but AG-UI gives us the schema and SDKs for free.

2. **Mid-run human input.** Our email auto-reply (Type 6) "approve
   before send" pattern is exactly the use case AG-UI was designed
   for. Today we implement it via a queue + a separate approval
   page. AG-UI would let the agent pause mid-run, surface the draft
   inline, and resume on user response. Cleaner UX, more complex
   backend.

3. **Future agentic chat surface.** If we ever build a chat-style
   "talk to your agent" UI (the `conversations` /
   `conversation_messages` tables are reserved for this but
   currently unused), AG-UI is the default protocol we'd reach for.

None of these are urgent. Each could be hand-rolled when the time
comes. The value of adopting AG-UI is *standards conformance* — our
backend works with any AG-UI-aware frontend, our frontend can consume
any AG-UI-aware backend. We have neither today.

## Recommendation

**Ignore AG-UI for now.** Revisit specifically when one of the
following triggers happens:

- We decide to ship real-time agent progress in the UI for Type 7
  (then evaluate AG-UI vs hand-rolled SSE).
- We decide to make Type 6 "approve before send" feel more like a
  conversation with the agent (then AG-UI's human-in-the-loop pattern
  is worth the integration cost).
- We adopt one of the frameworks that already speaks AG-UI
  (LangGraph, Pydantic AI, etc.) — which would itself be a bigger
  decision than picking a wire protocol.

**Things to do instead, in priority order:**

1. When user customization comes up, climb the **named-bundle
   ladder** (step 2 above) before considering user-supplied skill
   code (step 3). Users already shape Type 7 substantially via
   `analysis_goal` / `processing_steps`; bundles just package those.

2. If Apple Mail multi-user support becomes a priority, look at
   **remote MCP transport + per-user bridge daemons** — the
   architecturally honest solution. Not AG-UI.

## Codebase touchpoints referenced

- `backend/services/agentic_engine.py:286-326, 510-693`
- `backend/services/skills/registry.py:67-97`
- `backend/services/skills/__init__.py:19-21`
- `backend/services/workflows/analyze_data_collection.py`
- `backend/services/workflows/data_analyzer.py:73-160`
- `backend/services/mcp_client.py:22-48`
- `backend/api/workflows.py:656-733`
- `backend/alembic/versions/d3b6f9a2c4e7_seed_agentic_category_and_awf1_type.py:48-121`

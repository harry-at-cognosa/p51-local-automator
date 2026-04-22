# Learning Guide: Claude Code Agents

## What Is an Agent in Claude Code?

The term "agent" gets used loosely in AI. In Claude Code specifically, there are several related concepts:

### 1. Claude Code Itself Is an Agent
When you run Claude Code in the CLI, *it is* an agent -- it reads files, runs commands, makes decisions, and acts on your behalf. Every conversation with Claude Code is an agentic interaction.

### 2. Sub-Agents (Spawned Agents)
Claude Code can spawn **sub-agents** to handle specific tasks in parallel or isolation. These are created with the `Agent` tool and come in several types:

| Type | Purpose | Tools Available |
|------|---------|----------------|
| `general-purpose` | Complex multi-step tasks | All tools |
| `Explore` | Fast codebase searching | Read-only tools |
| `Plan` | Architecture and planning | Read-only tools |
| `claude-code-guide` | Claude Code documentation questions | Read + web tools |

### 3. Custom Skills as "Agents"
When we define a skill like `/analyze-data`, we're effectively creating a specialized agent -- Claude follows the skill's instructions with a specific purpose and constrained toolset.

### 4. Scheduled Agents (Triggers)
Agents that run on a schedule without user interaction. Created via `/schedule`. These run headless on Anthropic's infrastructure.

## How This Maps to Our Project

For our automation platform, we use "agent" to mean: **a configured automation that performs a specific task**, whether invoked interactively (skill), on a schedule (trigger), or as part of a workflow (chained).

Our `scripts/analyze_data.py` is the **agent logic** -- the actual intelligence that processes data. The skill definition is the **agent interface** -- how users and other agents invoke it.

## Agent Patterns We're Using

### Pattern 1: Skill + Script (Task 1)

```
User types /analyze-data
  -> Claude reads SKILL.md
  -> Claude runs analyze_data.py
  -> Script saves checkpointed outputs
  -> Claude reads outputs and presents summary
```

This is the simplest pattern: one skill, one script, sequential steps.

### Pattern 2: Scheduled Agent (Task 3 - coming)

```
Cron trigger fires daily at 8am
  -> Agent runs gmail_monitor.py
  -> Script reads Gmail via MCP
  -> Script categorizes and saves results
  -> Agent can email/alert based on findings
```

No human in the loop -- runs autonomously on schedule.

### Pattern 3: Agent Chaining (Task 4 - coming)

```
User types /list-events
  -> Agent 1: Email reader (scans for invitations)
  -> Output passed to Agent 2: Event parser (extracts event details)
  -> Output passed to Agent 3: Report generator (formats output)
```

Each agent is specialized. Output flows between them.

### Pattern 4: Workflow Orchestrator (Task 5 - coming)

```
User types /run-workflow sales-analysis
  -> Step 1: Ingest agent
  -> Checkpoint saved, status updated
  -> Step 2: Analysis agent
  -> Checkpoint saved -> PAUSE for user approval
  -> User reviews, approves
  -> Step 3: Comparison agent
  -> ...and so on
```

The orchestrator manages state, checkpoints, and approval gates.

## The Agent Design Principle

**Separation of concerns:**

| Layer | Responsibility | Example |
|-------|---------------|---------|
| **Interface** (skill/trigger) | How the agent is invoked, what arguments it takes | `SKILL.md` |
| **Logic** (script) | Deterministic data processing, file I/O, API calls | `analyze_data.py` |
| **Judgment** (Claude) | Interpreting results, deciding what's important, presenting to user | Claude's response after running the script |

The script should be runnable and testable *without* Claude. Claude adds the interpretation layer on top.

## What We Learned Building Task 1

1. **Let the script do the heavy lifting.** Claude is great at judgment and presentation, but pandas is better at data processing. Don't try to have Claude write analysis code on the fly -- write it once in a script, test it, and have Claude invoke it.

2. **Checkpointing is the agent's safety net.** Each step saves output before the next runs. This isn't just for failure recovery -- it's how you build inspectable, debuggable agents. When something goes wrong in step 3, you can look at step 2's output to understand why.

3. **Auto-detection makes agents flexible.** Our script detects date columns, amount columns, and categories automatically. This means the same agent works on household transactions (5 columns) and Amazon retail orders (26 columns) without configuration changes.

4. **The skill definition is surprisingly simple.** Most of the intelligence is in the Python script. The skill just says "run this script, read the outputs, tell the user what you found." That's the right split.

## Sub-Agent Spawning (Advanced)

Claude Code can spawn sub-agents for parallel work:

```
# Claude Code internally does this when you use the Agent tool:
Agent({
  subagent_type: "Explore",
  prompt: "Find all files that handle authentication"
})
```

We'll use this in Task 5 (workflow orchestrator) where the orchestrator spawns specialized agents for each step.

## Next Topics

- **Guide 03 (Hooks):** Pre/post processing triggers for agent actions
- **Guide 04 (Scheduling):** Running agents on cron schedules
- **Guide 05 (MCP):** Connecting agents to Gmail, Calendar, Sheets
- **Guide 06 (Workflows):** Chaining agents into multi-step pipelines with approval gates

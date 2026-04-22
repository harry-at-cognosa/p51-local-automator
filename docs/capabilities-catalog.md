## Purpose

Maps each example automation to the Claude Code features it demonstrates. This is the master reference for understanding what we're building and what it teaches.

---

## Claude Code Capabilities Being Demonstrated

| Capability | What It Is | Where We Learn It |
|-----------|-----------|-------------------|
| **Custom Skills** | Markdown-defined commands invoked with `/skill-name` in Claude Code CLI | Task 1 (first), all tasks |
| **Special-Purpose Agents** | Agent definitions with specific roles and tool access | Tasks 1-4 |
| **Scheduled Triggers** | Cron-based jobs that run agents on a schedule via `/schedule` | Tasks 2, 3 |
| **MCP Integrations** | Model Context Protocol servers for Gmail, Calendar, Sheets | Tasks 1, 3, 4 |
| **Hooks** | Pre/post processing shell commands triggered by tool calls | Task 2 |
| **Agent Chaining** | One agent's output feeds into another agent | Task 4 |
| **Multi-Step Workflows** | Pipelines with checkpointing, intermediate outputs saved per step | Task 1 (as workflow), Task 5 |
| **Human-in-the-Loop** | Async approval gates where user reviews, modifies, skips, or stops | Task 1 workflow, Task 5 |
| **Workflow Distribution** | End-of-workflow actions: email reports, write to Sheets, alert via Slack | Task 5 |

---

## Task-to-Capability Matrix

| Task | Custom Skill | Agent | Scheduling | MCP | Hooks | Chaining | Workflow |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1. Transaction Data Analyzer | /analyze-data | data-analysis | -- | Google Sheets | -- | -- | checkpointed pipeline |
| 2. SQL Query Runner | /run-query | sql-query | cron trigger | -- | post-query validation | -- | -- |
| 3. Gmail Topic Monitor | /check-email | gmail-monitor | daily trigger | Gmail | -- | -- | -- |
| 4. Meeting/Event Extractor | /list-events | event-extractor | -- | Gmail + Calendar | -- | email -> parser -> reporter | -- |
| 5. Sales Analysis Workflow | /run-workflow | orchestrator | -- | Sheets + Gmail | -- | multi-agent | full 5-step with approval gates |

---

## Implementation Order & Learning Progression

### Phase 2: Task 1 -- Transaction Data Analyzer
**New capabilities learned:**
- How to define a custom skill (markdown format, frontmatter, parameters)
- How to define a special-purpose agent
- Working with local files (CSV, Excel) from Claude Code
- Generating formatted Excel output with openpyxl
- Generating charts with matplotlib
- Storing artifacts in designated output paths

**Documented in:** `guides/01-skills.md`, `guides/02-agents.md`

### Phase 3: Task 3 -- Gmail Topic Monitor
**New capabilities learned:**
- MCP server configuration (Gmail)
- OAuth authentication flow for Google services
- Scheduled triggers via `/schedule`
- Running agents on a recurring basis
- Writing to Google Sheets via MCP

**Documented in:** `guides/04-scheduling.md`, `guides/05-mcp-integrations.md`

### Phase 4a: Task 2 -- SQL Query Runner
**New capabilities learned:**
- Database connectivity from Claude Code agents
- Hooks (post-query validation/logging)
- Saved query management
- Combining scheduling with database operations

**Documented in:** `guides/03-hooks.md`

### Phase 4b: Task 4 -- Meeting/Event Extractor
**New capabilities learned:**
- Agent chaining (output of one agent as input to another)
- Google Calendar MCP integration
- Multi-source data aggregation (email + calendar)
- Complex report formatting

**Documented in:** updates to existing guides

### Phase 4c: Task 5 -- Sales Analysis Workflow (Multi-Step Pipeline)
**New capabilities learned:**
- Multi-step workflow orchestration with checkpointing
- Human-in-the-loop approval gates (pause, review, modify, skip, continue)
- Workflow state persistence (run tracking, step results, parameter modification)
- Distribution actions (email results, write to Sheets, alert channels)
- Composing Tasks 1 + 2 into a larger business workflow

**Documented in:** `guides/06-workflows.md`

---

## Future Tasks (Capabilities They Would Add)

| Future Task | New Capability |
|------------|---------------|
| 6. Document Summarizer | File watching, PDF/DOCX parsing |
| 7. Expense Report Preparer | Template generation, receipt parsing |
| 8. Weekly Status Report | Agent orchestration (fan-out/fan-in), multi-source aggregation |
| 9. Slack/Teams Monitor | Additional MCP server integration |

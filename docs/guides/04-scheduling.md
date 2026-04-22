# Learning Guide: Scheduled Triggers

## What Are Scheduled Triggers?

A **scheduled trigger** (also called a "remote agent") runs a Claude Code agent on a cron schedule without user interaction. Think of it as a cron job where the worker is Claude -- it can read files, call MCP tools, run scripts, and produce output on a timer.

Use cases:
- Run the Gmail monitor daily at 8am to categorize overnight emails
- Generate a weekly sales report every Monday morning
- Check a database for anomalies every hour

## How to Set Up a Scheduled Trigger

### Using the `/schedule` Skill

Claude Code has a built-in `/schedule` skill for managing triggers. Invoke it with:

```
/schedule create "Check Gmail for new emails, categorize by topic, and save report" --cron "0 8 * * *"
```

Or ask in natural language:
```
/schedule
```
Then describe what you want: "Run the Gmail monitor every day at 8am Pacific"

### Cron Expression Syntax

```
┌───────── minute (0-59)
│ ┌─────── hour (0-23, UTC)
│ │ ┌───── day of month (1-31)
│ │ │ ┌─── month (1-12)
│ │ │ │ ┌─ day of week (0-6, Sunday=0)
│ │ │ │ │
* * * * *
```

Common examples:
| Expression | Meaning |
|-----------|---------|
| `0 8 * * *` | Every day at 8:00 AM UTC |
| `0 15 * * *` | Every day at 8:00 AM Pacific (UTC-7) |
| `0 8 * * 1` | Every Monday at 8:00 AM UTC |
| `0 */6 * * *` | Every 6 hours |
| `30 7 1 * *` | 7:30 AM on the 1st of each month |

**Note:** Cron times are in UTC. Adjust for your timezone.

### Managing Triggers

```
/schedule list          # See all scheduled triggers
/schedule run <id>      # Manually run a trigger now
/schedule delete <id>   # Remove a trigger
```

## How Triggers Execute

Scheduled triggers run on **Anthropic's infrastructure**, not your local machine. This means:

1. Your machine doesn't need to be on
2. The agent runs in a clean environment each time
3. It has access to MCP connectors you've authenticated (Gmail, Calendar, etc.)
4. It can write output files and send notifications

### What a Trigger Can Do

- Call MCP tools (Gmail, Calendar, Sheets)
- Run analysis and generate reports
- Create and save files
- Send email drafts (via Gmail MCP)
- Anything Claude Code can do non-interactively

### What a Trigger Cannot Do

- Ask the user questions (no human in the loop during execution)
- Access your local filesystem directly (runs remotely)
- Use tools that require interactive approval

## Designing for Scheduled Execution

When building an automation that will run on a schedule, design it to be **fully autonomous**:

1. **No user prompts** -- all parameters come from config or defaults
2. **Idempotent** -- running twice shouldn't cause problems
3. **Self-documenting output** -- save a run log alongside the results
4. **Error resilient** -- handle MCP outages gracefully, save partial results
5. **Time-aware** -- know what "since last run" means (track last run timestamp)

### Example: Gmail Monitor as a Scheduled Trigger

The trigger prompt would be something like:

> "Search Gmail for emails from the last 24 hours. Categorize each email into these topics: Business & Finance, Technology & AI, Personal & Social, Marketing & Promotions, Government & Institutional. Flag urgent items. Save the categorized results as JSON and generate an Excel report in the output directory. Include a summary of urgent items at the top."

This is the same thing our `/check-email` skill does, but without any user interaction.

## Scheduling vs. Hooks vs. Skills

| Feature | When It Runs | Who Triggers It | Interactive? |
|---------|-------------|-----------------|-------------|
| **Skill** | On demand | User types `/skill-name` | Yes |
| **Hook** | Before/after a tool call | Automatically by Claude Code | No |
| **Trigger** | On a cron schedule | Timer (Anthropic infrastructure) | No |

These compose together:
- A **skill** can set up a **trigger** (`/schedule create ...`)
- A **trigger** runs the same logic a skill would, but autonomously
- A **hook** can fire after a trigger completes (e.g., post-processing)

## Our Plan for Task 3

The Gmail monitor will work in two modes:

1. **Ad-hoc** (skill): User types `/check-email --period "last 7 days"` -- interactive, Claude presents results
2. **Scheduled** (trigger): Runs daily at 8am, saves output, optionally emails a summary

Both modes use the same categorization logic. The difference is just how they're invoked and whether a human sees the results in real-time.

## Gotchas & Lessons Learned

*(To be updated as we implement scheduling)*

1. **UTC times** -- Cron expressions are in UTC. Don't forget to convert from your local timezone.
2. **Remote execution** -- Triggers run on Anthropic's servers, not locally. Design accordingly.
3. **MCP auth must be active** -- If your Gmail OAuth token expires, the trigger will fail. Re-authenticate via `/mcp` if needed.
4. **No local file access** -- Since triggers run remotely, they can't read files on your laptop. Use MCP connectors for data sources, or plan for cloud-accessible storage.

## Next Steps

- Set up our first scheduled trigger for the Gmail monitor (after MCP proxy is stable)
- Test the trigger fires and produces output
- Document the full trigger lifecycle (create, monitor, troubleshoot, delete)

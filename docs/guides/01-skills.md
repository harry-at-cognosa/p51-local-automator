# Learning Guide: Claude Code Custom Skills

## What Is a Skill?

A **skill** is a custom slash command you define for Claude Code. When you type `/analyze-data` in the CLI, Claude loads your skill definition and follows its instructions. Skills are the simplest way to teach Claude Code new capabilities specific to your project.

Think of a skill as a **prompt template with superpowers**: it can reference files, invoke tools, run scripts, and accept user arguments.

## Where Skills Live

Skills are markdown files in a specific directory structure:

| Level | Location | Scope |
|-------|----------|-------|
| **Project** | `.claude/skills/<name>/SKILL.md` | This project only |
| **Personal** | `~/.claude/skills/<name>/SKILL.md` | All your projects |
| **Legacy** | `.claude/commands/<name>.md` | Project (older format) |

For this project, our skills live in `.claude/skills/`.

## Anatomy of a Skill Definition

A skill is a markdown file with YAML frontmatter:

```yaml
---
name: analyze-data                    # Becomes the /slash-command
description: Analyze transaction...   # When Claude should auto-suggest this skill
allowed-tools: Bash(python3 *), Read  # Which tools the skill can use
argument-hint: <file-path> [--start YYYY-MM-DD]  # Help text for arguments
---

# Skill Title

Instructions for Claude go here in markdown...

Use $ARGUMENTS to reference what the user typed after /analyze-data.
Use $ARGUMENTS[0] for the first argument specifically.
Use ${CLAUDE_SKILL_DIR} for the skill's own directory path.
```

### Key Frontmatter Fields

- **`name`** -- The slash command name. If omitted, the directory name is used.
- **`description`** -- Critical for discoverability. Claude uses this to decide when to suggest the skill. Write it like you're explaining to a colleague when to use this tool.
- **`allowed-tools`** -- Restricts which Claude Code tools the skill can invoke. Use patterns like `Bash(python3 *)` to allow running Python scripts.
- **`argument-hint`** -- Shows the user what arguments the skill expects.

### Substitution Variables

| Variable | Expands To |
|----------|-----------|
| `$ARGUMENTS` | Everything the user typed after the command |
| `$ARGUMENTS[0]`, `$ARGUMENTS[1]`, ... | Specific arguments by position |
| `${CLAUDE_SKILL_DIR}` | Absolute path to the skill's directory |
| `${CLAUDE_SESSION_ID}` | Current session identifier |

## Our First Skill: `/analyze-data`

**File:** `.claude/skills/analyze-data/SKILL.md`

This skill:
1. Accepts a file path and optional date range arguments
2. Tells Claude to run `scripts/analyze_data.py` with those arguments
3. Instructs Claude to review each step's output and present a summary

### What the Skill Does vs. What the Script Does

This is an important distinction:

- **The skill definition** tells Claude *what to do* -- it's instructions in natural language
- **The Python script** does the actual data processing -- pandas, openpyxl, matplotlib
- Claude acts as the **orchestrator**: it runs the script, reads the outputs, and presents findings to the user in a conversational way

The skill doesn't need to contain Python code. It just needs to tell Claude how to invoke the script and what to do with the results.

### Design Choices We Made

1. **Heavy lifting in Python, orchestration in the skill** -- The script handles data processing because that's deterministic and testable. Claude handles interpretation and presentation because that's where LLM judgment adds value.

2. **Checkpointed outputs** -- Each step saves files before the next step runs. If step 3 fails, you still have step 1 and 2 outputs. This is the foundation of our workflow pattern.

3. **Auto-detection** -- The script detects date columns, amount columns, and categories automatically rather than requiring the user to specify them. This makes it work across different datasets without configuration.

## How to Invoke

```
/analyze-data /path/to/data.csv --start 2025-01-01 --end 2025-06-30
/analyze-data /path/to/data.xlsx --after 2025-01-01
/analyze-data /path/to/data.csv --start 2025-01-01 --days 90
```

## Testing Results

We tested with three very different datasets:

| Dataset | Columns | Rows | Key Field Selector | Charts | Quality |
|---------|---------|------|-------------------|--------|---------|
| Household transactions (CSV) | 5 | 18,338 | Kept all 5 (all meaningful) | 3 charts with prior-period | 38 issues (duplicates + outliers) |
| Amazon retail orders (XLSX) | 26 | 5,482 | Dropped 8 -> kept 18 | 2 charts (no prior period) | Flagged quality issues |
| Ad spend by channel (XLSX) | 7 | 1,822 | Kept all 7 | 3 charts with prior-period | Flagged outliers |

The key-field selector correctly identified and dropped: constant-value columns (currency, prod_condition), address fields, long product descriptions, and columns with >80% nulls.

## Gotchas & Lessons Learned

1. **CSV parsing errors** -- Real-world CSV files often have trailing bad lines. Use `on_bad_lines='skip'` in pandas.
2. **Amount formatting** -- Financial data often has commas in numbers (e.g., "-6,633.66"). Must strip commas before converting to numeric.
3. **Date column detection** -- Column naming varies wildly ("Date", "order_day", "WkEnd_Date"). We use keyword matching + validation (can >80% of values parse as dates?).
4. **Matplotlib backend** -- Must set `matplotlib.use("Agg")` before importing pyplot when running non-interactively (no display).

## Next Steps

- Add Google Sheets as an input source (requires MCP integration -- see guide 05)
- Wire this into a multi-step workflow with approval gates (see guide 06)
- Add the skill to a scheduled trigger for automated reporting (see guide 04)

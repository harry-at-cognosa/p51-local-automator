# Workflow Types 2 & 4 — End-to-End Certification

**Date:** 2026-04-26
**Scope:** Track A of the roadmap review in `p51-local-automator_260426_sttus_and_plans.md`. Both types had complete engines (`backend/services/workflows/data_analyzer.py`, `sql_runner.py`) and dispatch wiring but had not been driven against real data.

## Verdict

Both types are **functional end-to-end**. Happy paths produce real artifacts; failure paths fail cleanly. None of the rough edges below blocks productive use, but several should be addressed before either type is held up as a polished example.

---

## Test data

| Type | Source | Size |
|---|---|---|
| 2 (Transaction Data Analyzer) | `/Users/harry/5_sample_agentic_apps/test_data/household_trans_2016-2026_18338rows.csv` | 18,338 rows × 5 cols (Date, Account, Payee, Category, Amount), 2016-01-01 → 2026-04-25 |
| 4 (SQL Query Runner) | Local Postgres `amazonst1` (same creds as `p51_automator`), schema `public`, two tables: `retail_sales_1e` (5,415 rows, dates 1998-2025) and `retail_sales_2a` (3,531 rows, dates 1998-2021) — overlapping timeframes, different schemas. |

---

## Type 2 — Transaction Data Analyzer

### Runs

| Workflow | Scenario | Result |
|---|---|---|
| 124 / run 45 | Happy path: full CSV, no date filter | ✅ completed in 1.7s, 6 artifacts (3× MD report, 1× XLSX filtered data, 2× PNG charts), all `file_exists=true` |
| 125 / run 46 | `file_path` set to nonexistent path | ✅ failed, `error_detail`: `"Data file not found: /nonexistent/path/no_such_file.csv"` |
| 126 / run 47 | Empty config | ✅ failed, `error_detail`: `"Data file not found: "` |

### Rough edges (rank-ordered)

1. **No LLM step.** `llm_tokens_used: 0` across the entire run. The `analysis` category implies LLM-driven narrative output (and Harry's status doc framed it that way), but type 2's engine just shells out to `analyze_data.py` and records artifacts. Type 4 already has the right pattern — a step 2 that reads the data summary and produces structured JSON (`summary`, `findings`, `anomalies`, `suggested_charts`). Recommended: port that pattern. Inputs to the LLM step would be `step1_data_profile.md` + `step3_summary_report.md`.
2. **`Category` column was ignored despite literally being named "Category".** `detect_category_columns()` (`scripts/analyze_data.py:124-135`) requires `2 <= nunique <= 50`. The Category column has 248 distinct values so it was dropped; the breakdown chart grouped by `Account` (8 values) instead. Two reasonable fixes: (a) lift the cap when the column name explicitly matches "category", showing the top-N values, or (b) expose `key_fields` in the workflow config so the user can override detection.
3. **`default_config` misaligned with the engine's actual keys.** The type's seeded `default_config` is `{date_range, key_fields, output_format}`. The engine reads `file_path, start_date, end_date, days, key_fields`. `file_path` (the load-bearing key) is missing from defaults; `date_range` and `output_format` are present but unread. Frontend `WorkflowConfigForm` likely papers over this for the user but it's still misleading. Recommended: sync `default_config` to the keys the engine actually reads.
4. **Empty-config error message** is `"Data file not found: "` (trailing space, empty path). Functional but a clearer message like `"Missing 'file_path' in workflow config"` would help non-developer users.
5. **Single workflow step** — the script does four internal sub-steps (Profile / Filter / Analyze / Quality) but `total_steps: 1`. For 18k rows this completes in 1.7s so it doesn't matter; for larger files, exposing the four sub-steps would give better progress feedback. Future enhancement.
6. **Hardcoded 120-second subprocess timeout** (`data_analyzer.py:60`). Fine for current scale; will be tight at million-row scale.

### Verified, working as designed

- BOM in CSV (UTF-8 with BOM) is handled correctly — date column detected as `Date`, not `﻿Date`.
- Outlier detection (3-sigma) caught all the obvious large transfers and consulting income.
- Date range auto-detected: 2016-01-01 to 2026-04-25.
- All artifacts written to `data/{group_id}/{user_id}/{workflow_id}/{run_id}/` per project convention.
- Step `output_summary` captures the script's stdout (truncated at 500 chars).

---

## Type 4 — SQL Query Runner

### Runs

| Workflow | Scenario | Result |
|---|---|---|
| 127 / run 48 | Happy path: 6-column GROUP BY against `retail_sales_2a` | ✅ completed in 12.9s (0.5s SQL + 11.9s LLM), 208 rows, 3 artifacts (CSV, XLSX, JSON analysis); LLM produced 6 findings + 5 anomalies including catching that `category=''` rows passed my `IS NOT NULL` filter |
| 131 / run 52 | CTE + UNION ALL across both tables (annual order counts) | ✅ completed in 9.5s, 28 rows, 3 artifacts; LLM noticed "2025 data may be partial" (correct — table cuts off mid-year) |
| 128 / run 49 | `UPDATE retail_sales_2a SET …` | ✅ rejected, `error_detail`: `"Query rejected: only SELECT/WITH/EXPLAIN queries are allowed"` |
| 129 / run 50 | `DROP TABLE retail_sales_2a` | ✅ same rejection |
| 130 / run 51 | Empty config | ✅ failed, `error_detail`: `"Missing connection_string or query in config"` |

### Rough edges (rank-ordered)

1. **`connection_string` is stored as plaintext in `user_workflows.config` JSON.** Real security concern for any non-toy use (DB passwords sit in the DB in cleartext, visible to anyone with table access). Two reasonable directions: (a) encrypt the JSON column at rest, or (b) introduce a separate `connections` table referenced by name from the workflow config (the more usable shape — a connection can be reused across workflows and rotated independently). Defer to a follow-up; not Track A.
2. **No "plain English → SQL" feature** that Harry's status doc explicitly called out. Currently the user must hand-write the SQL string. This is a much larger feature than a config-shape fix — the user effectively wants an LLM step *before* execution that translates intent + schema + dialect into SQL. Probably belongs in the future agentic category rather than as a type 4 enhancement. Flagged as a future-roadmap item, not a Track A fix.
3. **`default_config` misaligned with the engine's keys** (same shape as type 2). Type's defaults: `{database, query, output_format}`. Engine reads: `connection_string, query, query_name`. `database` is unused; `connection_string` is the actual load-bearing key but not surfaced in defaults. Recommended: sync.
4. **No SQL dialect hint** in config. Pandas + SQLAlchemy handles execution across dialects, but the LLM-analysis prompt doesn't know which dialect, which limits its usefulness for dialect-specific anomalies (Postgres array types, MSSQL date functions, etc.). Future config knob.
5. **No charts rendered** despite the LLM returning `suggested_charts`. Currently a "what you should plot" list, not actual plots. Future enhancement: feed the suggestions back through matplotlib (mirroring what `analyze_data.py` does for type 2).
6. **50-row LLM sample is unparameterized** (`sql_runner.py:91`). Fine default; future config knob.

### Verified, working as designed

- Read-only validation rejects `UPDATE`, `DROP`, etc. (`READONLY_PATTERN` + `DANGEROUS_PATTERN`).
- `WITH` (CTE) queries work — exercised both the `^WITH` regex match and a real CTE+UNION across two tables with different schemas.
- Connection string validation: `postgresql://` (sync driver) works correctly with `pandas.read_sql` + `create_engine`. The `+asyncpg` async variant from the main app's URL would NOT work here; sync URLs only. Worth documenting if the type ever gets a UI form.
- Step 1 (`Execute SQL query`) and step 2 (`Analyze results`) are correctly separated. Run-detail page shows both.
- LLM analysis JSON is well-formed and returns the expected keys (`summary, findings, anomalies, suggested_charts`).

---

## Fixes applied in this session

Three of the rough edges above were small enough to fix inline:

1. **Lifted Category-column cap in `scripts/analyze_data.py`** from `nunique <= 50` to `nunique <= 500` for naming-matched columns. Re-run on workflow 124 (run 53) now produces a `Distribution by Category` block in the summary report (Household 17.9%, Groceries 17.7%, Business Expenses subcategories, etc.) alongside `Distribution by Account`.
2. **Synced `default_config` for types 2 and 4 in `backend/db/seed.py`.** Type 2 now exposes `{file_path, start_date, end_date, days, key_fields}`; type 4 now exposes `{connection_string, query, query_name}`. Restart triggers the seed upsert; verified via `GET /workflow-types`. Frontend forms that key off `default_config` now show the right fields.
3. **Added an LLM narrative step to type 2** (`backend/services/workflows/data_analyzer.py`). Mirrors `sql_runner.py`'s pattern: after the script step, reads `step1_data_profile.md` + `step3_summary_report.md` and calls `llm_service.judge_structured`, writing `step5_llm_analysis.json` as a recorded artifact. Run 53 reports `llm_tokens_used=1572`, 6 findings, and the LLM correctly flagged that the data extends into 2026 (a real future-dated period in the source). Also tightened the empty-config error to `"Missing 'file_path' in workflow config"` instead of the prior trailing-space message.

## Follow-up tickets remaining

These are the rough edges above that were NOT addressed inline:

1. **Move `connection_string` out of plaintext JSON.** Larger; touches schema + UI + auth model. Probably its own design pass.
2. **"Plain English → SQL" for type 4.** Belongs in the agentic category direction (Track C in the plan), not as a type-4 enhancement.
3. **Expose internal sub-steps of `analyze_data.py` as workflow steps** (Profile / Filter / Analyze / Quality). Future progress-tracking enhancement — only matters at much larger data volumes than the current test data.
4. **No SQL dialect hint** in type 4 config; **no chart rendering** of LLM-suggested charts in type 4. Both are minor future config knobs.
5. **Hardcoded 120s subprocess timeout** for `analyze_data.py`. Fine at current scale.

None of these block calling types 2 and 4 "certified" for the existing functionality.

---

## Artifacts on disk (for reference)

- Type 2 happy path: `data/1/1/124/45/{step1_data_profile.md, step2_filtered_data.xlsx, step3_summary_report.md, step3_chart_by_category.png, step3_chart_trend.png, step4_quality_report.md}`
- Type 4 category breakdown: `data/1/1/127/48/{category_totals_2a_results.csv, category_totals_2a_results.xlsx, category_totals_2a_analysis.json}`
- Type 4 cross-table CTE: `data/1/1/131/52/{annual_orders_results.csv, annual_orders_results.xlsx, annual_orders_analysis.json}`

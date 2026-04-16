"""SQL Query Runner Workflow

Steps:
1. Execute read-only SQL query
2. Analyze results with LLM
3. Save results as CSV/Excel

Config (from user_workflows.config):
    connection_string: str - SQLAlchemy connection string
    query: str - SQL query to execute
    query_name: str - Optional name for the query
"""
import json
import os
import re

import pandas as pd
from sqlalchemy import create_engine, text

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import llm_service
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import UserWorkflows, WorkflowRuns

log = get_logger("sql_runner")

READONLY_PATTERN = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)
DANGEROUS_PATTERN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b", re.IGNORECASE)


def validate_readonly(sql: str) -> bool:
    """Reject anything that isn't a SELECT/WITH/EXPLAIN."""
    if DANGEROUS_PATTERN.search(sql):
        return False
    if not READONLY_PATTERN.match(sql):
        return False
    return True


async def run_sql_runner(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute SQL query and analyze results."""
    config = workflow.config or {}
    connection_string = config.get("connection_string", "")
    query = config.get("query", "")
    query_name = config.get("query_name", "query")

    if not connection_string or not query:
        run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger)
        await engine.fail_run(session, run, "Missing connection_string or query in config")
        return run

    if not validate_readonly(query):
        run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger)
        await engine.fail_run(session, run, "Query rejected: only SELECT/WITH/EXPLAIN queries are allowed")
        return run

    run = await engine.create_run(session, workflow.workflow_id, total_steps=2, trigger=trigger)
    output_dir = engine.get_run_output_dir(workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

    try:
        # ── Step 1: Execute query ─────────────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Execute SQL query")

        engine_db = create_engine(connection_string)
        with engine_db.connect() as conn:
            df = pd.read_sql(text(query), conn)

        rows, cols = df.shape

        # Save results
        csv_path = os.path.join(output_dir, f"{query_name}_results.csv")
        xlsx_path = os.path.join(output_dir, f"{query_name}_results.xlsx")
        df.to_csv(csv_path, index=False)
        df.to_excel(xlsx_path, index=False)

        await engine.record_artifact(session, run.run_id, step1.step_id, csv_path, "csv", f"Query results ({rows} rows)")
        await engine.record_artifact(session, run.run_id, step1.step_id, xlsx_path, "xlsx", f"Query results ({rows} rows)")

        await engine.complete_step(session, step1, output_summary=f"Query returned {rows} rows, {cols} columns")

        # ── Step 2: Analyze with LLM ─────────────────────────
        step2 = await engine.start_step(session, run.run_id, 2, "Analyze results")

        # Send first 50 rows to LLM for analysis
        sample = df.head(50).to_string(index=False)
        stats = df.describe().to_string()

        system = """You are a data analysis assistant. You will receive SQL query results.
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

Return ONLY the JSON, no other text."""

        user_prompt = f"""Query: {query}

Results: {rows} rows, {cols} columns
Columns: {', '.join(df.columns.tolist())}

Statistics:
{stats}

Sample data (first 50 rows):
{sample}"""

        llm_result = llm_service.judge_structured(system, user_prompt)
        analysis = llm_result["result"]
        usage = llm_result["usage"]
        total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        analysis_path = os.path.join(output_dir, f"{query_name}_analysis.json")
        with open(analysis_path, "w") as f:
            json.dump(analysis, f, indent=2)

        await engine.record_artifact(session, run.run_id, step2.step_id, analysis_path, "json", "LLM analysis")

        findings_count = len(analysis.get("findings", []))
        await engine.complete_step(session, step2, output_summary=f"{findings_count} findings identified", llm_tokens=total_tokens)

        await engine.complete_run(session, run)
        log.info("sql_runner_complete", run_id=run.run_id, rows=rows)
        return run

    except Exception as e:
        log.error("sql_runner_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

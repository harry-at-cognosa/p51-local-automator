"""Transaction Data Analyzer Workflow

Steps:
1. Run analyze_data.py script (profile, filter, analyze, charts, quality report)
2. Summarize findings with LLM

Config (from user_workflows.config):
    file_path: str - Path to CSV or Excel file
    start_date: str - Optional start date filter
    end_date: str - Optional end date filter
    days: int - Optional days filter
    key_fields: list[str] - Optional key field overrides
    output_format: str - "xlsx" (default)
"""
import json
import os
import subprocess

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import UserWorkflows, WorkflowRuns

log = get_logger("data_analyzer")

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "scripts")


async def run_data_analyzer(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the data analysis pipeline."""
    config = workflow.config or {}
    file_path = config.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger)
        await engine.fail_run(session, run, f"Data file not found: {file_path}")
        return run

    run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger)
    output_dir = engine.get_run_output_dir(workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

    try:
        # ── Step 1: Run analysis script ───────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Analyze data")

        script = os.path.join(SCRIPTS_DIR, "analyze_data.py")
        cmd = ["python3", script, file_path, "--output-dir", output_dir]

        if config.get("start_date"):
            cmd.extend(["--start", config["start_date"]])
        if config.get("end_date"):
            cmd.extend(["--end", config["end_date"]])
        if config.get("days"):
            cmd.extend(["--days", str(config["days"])])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            await engine.fail_step(session, step1, f"Script failed: {result.stderr[:500]}")
            await engine.fail_run(session, run, "Analysis script failed")
            return run

        # Record all generated artifacts
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if fname.endswith(".xlsx"):
                await engine.record_artifact(session, run.run_id, step1.step_id, fpath, "xlsx", "Filtered data")
            elif fname.endswith(".png"):
                await engine.record_artifact(session, run.run_id, step1.step_id, fpath, "png", f"Chart: {fname}")
            elif fname.endswith(".md"):
                await engine.record_artifact(session, run.run_id, step1.step_id, fpath, "md", f"Report: {fname}")

        await engine.complete_step(session, step1, output_summary=result.stdout.strip()[:500])
        await engine.complete_run(session, run)
        log.info("data_analyzer_complete", run_id=run.run_id)
        return run

    except Exception as e:
        log.error("data_analyzer_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

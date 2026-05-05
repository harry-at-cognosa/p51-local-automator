"""Transaction Data Analyzer Workflow

Steps:
1. Run analyze_data.py script (profile, filter, analyze, charts, quality report)
2. Summarize findings with LLM (consumes the script's markdown reports)

Config (from user_workflows.config):
    file_path: str - Path to CSV or Excel file
    start_date: str - Optional start date filter
    end_date: str - Optional end date filter
    days: int - Optional days filter
    key_fields: list[str] - Optional key field overrides
"""
import json
import os
import subprocess

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import llm_service, workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import UserWorkflows, WorkflowRuns

log = get_logger("data_analyzer")

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "scripts")

LLM_SYSTEM_PROMPT = """You are a data analysis assistant. You will receive a data
profile and a statistical summary produced by an automated transaction analyzer.

Provide a brief narrative analysis. Return JSON with these keys:
{
    "summary": "1-2 sentence overview of what the data shows",
    "findings": ["bulleted finding 1", "bulleted finding 2", ...],
    "anomalies": ["notable outlier or data quality issue 1", ...],
    "suggested_charts": ["chart type: brief description", ...]
}

Return ONLY the JSON, no other text."""


def _read_text_safe(path: str, max_chars: int = 8000) -> str:
    """Read a file if present; truncate to keep prompts compact."""
    try:
        with open(path) as f:
            return f.read()[:max_chars]
    except OSError:
        return ""


async def run_data_analyzer(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the data analysis pipeline."""
    config = workflow.config or {}
    file_path = config.get("file_path", "")
    if not file_path:
        run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger, config=workflow.config)
        await engine.fail_run(session, run, "Missing 'file_path' in workflow config")
        return run
    if not os.path.exists(file_path):
        run = await engine.create_run(session, workflow.workflow_id, total_steps=1, trigger=trigger, config=workflow.config)
        await engine.fail_run(session, run, f"Data file not found: {file_path}")
        return run

    run = await engine.create_run(session, workflow.workflow_id, total_steps=2, trigger=trigger, config=workflow.config)
    output_dir = await engine.get_run_output_dir(session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

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

        # ── Step 2: LLM narrative analysis ───────────────────
        step2 = await engine.start_step(session, run.run_id, 2, "Analyze findings")

        profile_text = _read_text_safe(os.path.join(output_dir, "step1_data_profile.md"))
        summary_text = _read_text_safe(os.path.join(output_dir, "step3_summary_report.md"))

        if not profile_text and not summary_text:
            await engine.complete_step(session, step2, output_summary="Skipped: no profile or summary report found")
            await engine.complete_run(session, run)
            return run

        user_prompt = f"""## Data Profile

{profile_text or "(profile not available)"}

## Analysis Summary

{summary_text or "(summary not available)"}"""

        llm_result = llm_service.judge_structured(LLM_SYSTEM_PROMPT, user_prompt)
        analysis = llm_result["result"]
        usage = llm_result["usage"]
        total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        analysis_path = os.path.join(output_dir, "step5_llm_analysis.json")
        with open(analysis_path, "w") as f:
            json.dump(analysis, f, indent=2)

        await engine.record_artifact(session, run.run_id, step2.step_id, analysis_path, "json", "LLM narrative analysis")

        findings_count = len(analysis.get("findings", [])) if isinstance(analysis, dict) else 0
        await engine.complete_step(session, step2, output_summary=f"{findings_count} findings identified", llm_tokens=total_tokens)

        await engine.complete_run(session, run)
        log.info("data_analyzer_complete", run_id=run.run_id, llm_tokens=total_tokens)
        return run

    except Exception as e:
        log.error("data_analyzer_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

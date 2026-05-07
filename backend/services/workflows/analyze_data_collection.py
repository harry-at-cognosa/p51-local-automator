"""AWF-1 runner — wires AgenticEngine into the WORKFLOW_RUNNERS dispatch.

Resolves the user's inputs sandbox + the run output dir, builds a
SkillContext, instantiates AgenticEngine, drives it through the six
stages, and finalizes the run.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns
from backend.services import workflow_engine as engine
from backend.services.agentic_engine import AgenticEngine, STAGES
from backend.services.logger_service import get_logger
from backend.services.skills import SkillContext

log = get_logger("analyze_data_collection")


async def run_analyze_data_collection(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Entry point invoked by api.workflows._run_workflow_background.

    total_steps is initialized to len(STAGES) (six). The engine bumps it
    to the actual step count via run_all() so the UI progress bar isn't
    pinned at 6/6 with 30 sub-step rows trailing."""
    run = await engine.create_run(
        session,
        workflow_id=workflow.workflow_id,
        total_steps=len(STAGES),
        trigger=trigger,
        config=workflow.config,
    )
    output_dir = await engine.get_run_output_dir(
        session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id
    )
    inputs_dir = await engine.get_user_inputs_dir(
        session, workflow.group_id, workflow.user_id
    )
    config = workflow.config or {}
    token_budget = await engine.resolve_int_setting(
        session,
        group_id=workflow.group_id,
        name=engine.SETTING_TOKEN_BUDGET,
        user_override=config.get("token_budget") if isinstance(config.get("token_budget"), (int, str)) else None,
    )

    ctx = SkillContext(run_id=run.run_id, artifacts_dir=output_dir)

    awf = AgenticEngine(
        session=session,
        run=run,
        workflow=workflow,
        ctx=ctx,
        inputs_dir=inputs_dir,
        token_budget=token_budget,
    )

    try:
        await awf.run_all()
        await engine.complete_run(session, run)
        log.info(
            "awf1_run_complete",
            run_id=run.run_id,
            workflow_id=workflow.workflow_id,
            n_steps=awf._step_counter,
            draft=awf.draft_report_path,
        )
        return run
    except Exception as e:
        log.error("awf1_run_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

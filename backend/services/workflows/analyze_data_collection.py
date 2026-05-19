"""AWF-1 runner — wires AgenticEngine into the WORKFLOW_RUNNERS dispatch.

Resolves the user's inputs sandbox + the run output dir, builds a
SkillContext, instantiates AgenticEngine, drives it through the
configured stage sequence, and finalizes the run.

Per the configurable-pipeline refactor (R1): workflow.config may set a
`stages` list to override the default six-stage AWF-1 sequence — useful
for variants that skip audit/scribe or that only need ingest+profile+
synthesize. When absent the engine falls back to DEFAULT_STAGES.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns
from backend.services import workflow_engine as engine
from backend.services.agentic_engine import (
    AgenticEngine,
    DEFAULT_STAGE_TIMEOUT_SECONDS,
    DEFAULT_STAGES,
)
from backend.services.logger_service import get_logger
from backend.services.skills import SkillContext

log = get_logger("analyze_data_collection")


def _resolve_stages(config: dict) -> tuple[str, ...]:
    """Resolve workflow.config.stages (list[str]) to a tuple, falling back
    to DEFAULT_STAGES. The Pydantic validator on UserWorkflowCreate/Update
    has already rejected unknown names and duplicates by the time we get
    here, but we defensively re-check both — a workflow row inserted via
    SQL (seed scripts, demo loader) won't have hit the validator."""
    raw = config.get("stages")
    if raw is None:
        return DEFAULT_STAGES
    if not isinstance(raw, list) or not raw:
        return DEFAULT_STAGES
    cleaned: list[str] = []
    for s in raw:
        if not isinstance(s, str) or s not in DEFAULT_STAGES:
            log.warning(
                "stages_override_invalid_entry_ignored",
                entry=s, defaulting_to=DEFAULT_STAGES,
            )
            return DEFAULT_STAGES
        if s in cleaned:
            log.warning(
                "stages_override_duplicate_entry_ignored",
                entry=s, defaulting_to=DEFAULT_STAGES,
            )
            return DEFAULT_STAGES
        cleaned.append(s)
    return tuple(cleaned)


async def run_analyze_data_collection(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Entry point invoked by api.workflows._run_workflow_background.

    total_steps is initialized to len(stages) (one row per stage marker).
    The engine bumps it to the actual step count via run_all() so the UI
    progress bar isn't pinned at <n>/<n> with sub-step rows trailing."""
    config = workflow.config or {}
    stages = _resolve_stages(config)
    run = await engine.create_run(
        session,
        workflow_id=workflow.workflow_id,
        total_steps=len(stages),
        trigger=trigger,
        config=workflow.config,
    )
    output_dir = await engine.get_run_output_dir(
        session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id
    )
    inputs_dir = await engine.get_user_inputs_dir(
        session, workflow.group_id, workflow.user_id
    )
    token_budget = await engine.resolve_int_setting(
        session,
        group_id=workflow.group_id,
        name=engine.SETTING_TOKEN_BUDGET,
        user_override=config.get("token_budget") if isinstance(config.get("token_budget"), (int, str)) else None,
    )
    stage_timeout = await engine.resolve_int_setting(
        session,
        group_id=workflow.group_id,
        name="stage_timeout_seconds",
        user_override=(
            config.get("stage_timeout_seconds")
            if isinstance(config.get("stage_timeout_seconds"), (int, str))
            else None
        ),
    )
    if stage_timeout is None:
        stage_timeout = DEFAULT_STAGE_TIMEOUT_SECONDS

    ctx = SkillContext(run_id=run.run_id, artifacts_dir=output_dir)

    awf = AgenticEngine(
        session=session,
        run=run,
        workflow=workflow,
        ctx=ctx,
        inputs_dir=inputs_dir,
        token_budget=token_budget,
        stage_timeout_seconds=stage_timeout,
        stages=stages,
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

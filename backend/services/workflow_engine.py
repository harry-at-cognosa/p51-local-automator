"""Workflow Engine — executes multi-step workflows with checkpointing.

Each workflow type defines a list of steps. The engine:
1. Creates a WorkflowRun record
2. Executes each step, saving a WorkflowStep record after each
3. Saves artifacts (files) and records them in WorkflowArtifacts
4. Updates the run status on completion or failure
"""
import os
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ApiSettings,
    GroupSettings,
    UserWorkflows,
    WorkflowArtifacts,
    WorkflowRuns,
    WorkflowSteps,
)
from backend.services.logger_service import get_logger

log = get_logger("workflow_engine")


SETTING_FILE_SYSTEM_ROOT = "file_system_root"


async def _resolve_file_system_root(session: AsyncSession, group_id: int) -> str:
    """Return the file_system_root for a group, falling back to the global default.

    Resolution chain (per Phase 1 plan):
      1. group_settings row for (group_id, 'file_system_root')
      2. api_settings row for 'file_system_root'
      3. RuntimeError — no silent fallback to a hardcoded path.
    """
    group_value = await session.scalar(
        select(GroupSettings.value).where(
            GroupSettings.group_id == group_id,
            GroupSettings.name == SETTING_FILE_SYSTEM_ROOT,
        )
    )
    if group_value:
        return group_value

    global_value = await session.scalar(
        select(ApiSettings.value).where(ApiSettings.name == SETTING_FILE_SYSTEM_ROOT)
    )
    if global_value:
        return global_value

    raise RuntimeError(
        f"file_system_root is not configured for group {group_id}; "
        "set group_settings or api_settings 'file_system_root'"
    )


async def get_run_output_dir(
    session: AsyncSession,
    group_id: int,
    user_id: int,
    workflow_id: int,
    run_id: int,
) -> str:
    """Return the filesystem path for a run's output files.

    Path layout: <file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/
    """
    root = await _resolve_file_system_root(session, group_id)
    path = os.path.join(root, str(group_id), str(user_id), str(workflow_id), str(run_id))
    os.makedirs(path, exist_ok=True)
    return path


async def get_workflow_inputs_dir(
    session: AsyncSession,
    group_id: int,
    user_id: int,
    workflow_id: int,
) -> str:
    """Return the filesystem path for a workflow's user-supplied input files.

    Path layout: <file_system_root>/{group_id}/{user_id}/{workflow_id}/inputs/

    Inputs are colocated under the workflow (not per-run) since users typically
    reuse the same inputs across runs of the same workflow.
    """
    root = await _resolve_file_system_root(session, group_id)
    path = os.path.join(root, str(group_id), str(user_id), str(workflow_id), "inputs")
    os.makedirs(path, exist_ok=True)
    return path


async def get_user_inputs_dir(
    session: AsyncSession,
    group_id: int,
    user_id: int,
) -> str:
    """Return the per-user filesystem root for input files reusable across workflows.

    Path layout: <file_system_root>/{group_id}/{user_id}/inputs/

    Files placed here are visible to every workflow owned by this user. Use this
    for input pickers; use get_workflow_inputs_dir() when a workflow needs its
    own private inputs space (e.g., per-workflow processed-files ledgers).
    """
    root = await _resolve_file_system_root(session, group_id)
    path = os.path.join(root, str(group_id), str(user_id), "inputs")
    os.makedirs(path, exist_ok=True)
    return path


async def create_run(
    session: AsyncSession,
    workflow_id: int,
    total_steps: int,
    trigger: str = "manual",
    config: dict | None = None,
) -> WorkflowRuns:
    """Create a new workflow run record.

    `config` should be the user_workflows.config in effect at run start.
    Stored verbatim in workflow_runs.config_snapshot so later edits to the
    workflow's config don't obscure what an earlier run actually used.
    """
    run = WorkflowRuns(
        workflow_id=workflow_id,
        status="running",
        current_step=0,
        total_steps=total_steps,
        trigger=trigger,
        config_snapshot=config,
    )
    session.add(run)
    await session.flush()
    return run


async def start_step(
    session: AsyncSession,
    run_id: int,
    step_number: int,
    step_name: str,
    stage: str | None = None,
    kind: str | None = None,
) -> WorkflowSteps:
    """Create a step record and mark it as running.

    `stage` and `kind` are the AWF-1 agentic annotations (NULL for
    types 1-6). Stage ∈ {ingest, profile, analyze, synthesize, audit,
    scribe}. Kind ∈ {skill_call, llm_turn, stage_marker}.
    """
    step = WorkflowSteps(
        run_id=run_id,
        step_number=step_number,
        step_name=step_name,
        status="running",
        started_at=datetime.now(timezone.utc),
        stage=stage,
        kind=kind,
    )
    session.add(step)
    await session.flush()

    # Update run's current step
    await session.execute(
        update(WorkflowRuns).where(WorkflowRuns.run_id == run_id).values(current_step=step_number)
    )
    await session.commit()
    return step


async def complete_step(
    session: AsyncSession,
    step: WorkflowSteps,
    output_summary: str = "",
    artifacts: dict | None = None,
    llm_tokens: int = 0,
):
    """Mark a step as completed."""
    step.status = "completed"
    step.completed_at = datetime.now(timezone.utc)
    step.output_summary = output_summary
    step.artifacts = artifacts
    step.llm_tokens_used = llm_tokens
    await session.commit()


async def fail_step(
    session: AsyncSession,
    step: WorkflowSteps,
    error: str,
):
    """Mark a step as failed."""
    step.status = "failed"
    step.completed_at = datetime.now(timezone.utc)
    step.error_detail = error
    await session.commit()


async def complete_run(session: AsyncSession, run: WorkflowRuns):
    """Mark a run as completed."""
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()

    # Update workflow's last_run_at
    await session.execute(
        update(UserWorkflows)
        .where(UserWorkflows.workflow_id == run.workflow_id)
        .values(last_run_at=run.completed_at)
    )
    await session.commit()


async def fail_run(session: AsyncSession, run: WorkflowRuns, error: str):
    """Mark a run as failed."""
    run.status = "failed"
    run.completed_at = datetime.now(timezone.utc)
    run.error_detail = error
    await session.commit()


async def record_artifact(
    session: AsyncSession,
    run_id: int,
    step_id: int | None,
    file_path: str,
    file_type: str,
    description: str = "",
) -> WorkflowArtifacts:
    """Record a generated file."""
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    artifact = WorkflowArtifacts(
        run_id=run_id,
        step_id=step_id,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        description=description,
    )
    session.add(artifact)
    await session.commit()
    return artifact

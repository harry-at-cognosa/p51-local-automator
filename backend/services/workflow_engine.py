"""Workflow Engine — executes multi-step workflows with checkpointing.

Each workflow type defines a list of steps. The engine:
1. Creates a WorkflowRun record
2. Executes each step, saving a WorkflowStep record after each
3. Saves artifacts (files) and records them in WorkflowArtifacts
4. Updates the run status on completion or failure
"""
import os
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import WORK_DIR
from backend.db.models import WorkflowRuns, WorkflowSteps, WorkflowArtifacts, UserWorkflows
from backend.services.logger_service import get_logger

log = get_logger("workflow_engine")


def get_run_output_dir(group_id: int, user_id: int, workflow_id: int, run_id: int) -> str:
    """Return the filesystem path for a run's output files."""
    path = os.path.join(WORK_DIR, "data", str(group_id), str(user_id), str(workflow_id), str(run_id))
    os.makedirs(path, exist_ok=True)
    return path


async def create_run(
    session: AsyncSession,
    workflow_id: int,
    total_steps: int,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Create a new workflow run record."""
    run = WorkflowRuns(
        workflow_id=workflow_id,
        status="running",
        current_step=0,
        total_steps=total_steps,
        trigger=trigger,
    )
    session.add(run)
    await session.flush()
    return run


async def start_step(
    session: AsyncSession,
    run_id: int,
    step_number: int,
    step_name: str,
) -> WorkflowSteps:
    """Create a step record and mark it as running."""
    step = WorkflowSteps(
        run_id=run_id,
        step_number=step_number,
        step_name=step_name,
        status="running",
        started_at=datetime.now(timezone.utc),
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

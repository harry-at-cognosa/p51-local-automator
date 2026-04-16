import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session, SqlAsyncSession
from backend.db.models import User, WorkflowTypes, UserWorkflows, WorkflowRuns, WorkflowSteps, WorkflowArtifacts
from backend.db.schemas import (
    WorkflowTypeRead, UserWorkflowCreate, UserWorkflowRead, UserWorkflowUpdate,
    WorkflowRunRead, WorkflowStepRead, WorkflowArtifactRead,
)
from backend.auth.users import current_active_user

router_workflows = APIRouter()


# ── Workflow Types (catalog) ─────────────────────────────────


@router_workflows.get("/workflow-types", response_model=list[WorkflowTypeRead])
async def list_workflow_types(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(
        select(WorkflowTypes).where(WorkflowTypes.enabled == True).order_by(WorkflowTypes.type_id)
    )
    return result.scalars().all()


# ── User Workflows (configured instances) ────────────────────


@router_workflows.get("/workflows", response_model=list[UserWorkflowRead])
async def list_workflows(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(
        select(UserWorkflows)
        .where(UserWorkflows.group_id == user.group_id)
        .order_by(UserWorkflows.created_at.desc())
    )
    return result.scalars().all()


@router_workflows.post("/workflows", response_model=UserWorkflowRead)
async def create_workflow(
    body: UserWorkflowCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    wf_type = await session.get(WorkflowTypes, body.type_id)
    if not wf_type or not wf_type.enabled:
        raise HTTPException(status_code=404, detail="Workflow type not found")

    workflow = UserWorkflows(
        user_id=user.user_id,
        group_id=user.group_id,
        type_id=body.type_id,
        name=body.name,
        config=body.config,
        schedule=body.schedule,
        enabled=body.enabled,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@router_workflows.get("/workflows/{workflow_id}", response_model=UserWorkflowRead)
async def get_workflow(
    workflow_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await session.get(UserWorkflows, workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router_workflows.put("/workflows/{workflow_id}", response_model=UserWorkflowRead)
async def update_workflow(
    workflow_id: int,
    body: UserWorkflowUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await session.get(UserWorkflows, workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(workflow, field, value)

    await session.commit()
    await session.refresh(workflow)
    return workflow


@router_workflows.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await session.get(UserWorkflows, workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await session.delete(workflow)
    await session.commit()
    return {"detail": "Workflow deleted"}


# ── Workflow Runs ────────────────────────────────────────────


@router_workflows.get("/workflows/{workflow_id}/runs", response_model=list[WorkflowRunRead])
async def list_runs(
    workflow_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await session.get(UserWorkflows, workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    result = await session.execute(
        select(WorkflowRuns)
        .where(WorkflowRuns.workflow_id == workflow_id)
        .order_by(WorkflowRuns.started_at.desc())
        .limit(50)
    )
    return result.scalars().all()


# ── Trigger a workflow run ───────────────────────────────────

WORKFLOW_RUNNERS = {
    1: "email_monitor",
    2: "data_analyzer",
    3: "calendar_digest",
    4: "sql_runner",
}


async def _run_workflow_background(workflow_id: int):
    """Run a workflow in the background with its own DB session."""
    async with SqlAsyncSession() as session:
        workflow = await session.get(UserWorkflows, workflow_id)
        if not workflow:
            return

        if workflow.type_id == 1:
            from backend.services.workflows.email_monitor import run_email_monitor
            await run_email_monitor(session, workflow, trigger="manual")
        elif workflow.type_id == 2:
            from backend.services.workflows.data_analyzer import run_data_analyzer
            await run_data_analyzer(session, workflow, trigger="manual")
        elif workflow.type_id == 3:
            from backend.services.workflows.calendar_digest import run_calendar_digest
            await run_calendar_digest(session, workflow, trigger="manual")
        elif workflow.type_id == 4:
            from backend.services.workflows.sql_runner import run_sql_runner
            await run_sql_runner(session, workflow, trigger="manual")


@router_workflows.post("/workflows/{workflow_id}/run", response_model=dict)
async def trigger_run(
    workflow_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await session.get(UserWorkflows, workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.type_id not in WORKFLOW_RUNNERS:
        raise HTTPException(status_code=400, detail=f"No runner for workflow type {workflow.type_id}")

    # Run in background so the API returns immediately
    background_tasks.add_task(_run_workflow_background, workflow_id)

    return {"detail": f"Workflow run triggered for '{workflow.name}'", "workflow_id": workflow_id}


# ── Run details (steps + artifacts) ─────────────────────────


@router_workflows.get("/runs/{run_id}", response_model=WorkflowRunRead)
async def get_run(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router_workflows.get("/runs/{run_id}/steps", response_model=list[WorkflowStepRead])
async def get_run_steps(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(WorkflowSteps).where(WorkflowSteps.run_id == run_id).order_by(WorkflowSteps.step_number)
    )
    return result.scalars().all()


@router_workflows.get("/runs/{run_id}/artifacts", response_model=list[WorkflowArtifactRead])
async def get_run_artifacts(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(WorkflowArtifacts).where(WorkflowArtifacts.run_id == run_id).order_by(WorkflowArtifacts.created_at)
    )
    return result.scalars().all()

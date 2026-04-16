from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, WorkflowTypes, UserWorkflows, WorkflowRuns
from backend.db.schemas import (
    WorkflowTypeRead, UserWorkflowCreate, UserWorkflowRead, UserWorkflowUpdate,
    WorkflowRunRead,
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

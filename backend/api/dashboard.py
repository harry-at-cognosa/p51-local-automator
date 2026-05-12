"""Dashboard read-only endpoints.

The /stats and /recent-runs endpoints share a single role-aware scope rule
(D.1, 2026-05-11):
    superuser              → no row filter (system-wide)
    groupadmin or manager  → filter to the user's group
    everyone else          → filter to the user's own user_id

The scope helper returns a list of SQLAlchemy where-clauses so callers can
splat them into the `where(...)` of any query that joins UserWorkflows.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.session import async_get_session
from backend.db.models import (
    User,
    UserWorkflows,
    WorkflowCategories,
    WorkflowRuns,
    WorkflowTypes,
)
from backend.db.schemas import DashboardStats
from backend.auth.users import current_active_user
from backend.services.scheduler_service import scheduler

router_dashboard = APIRouter(prefix="/dashboard")


def _run_scope_filter(user: User) -> list:
    """Return the where-clauses that scope a query joining UserWorkflows
    to the runs/workflows the current user should be able to see.

    Returns an empty list for superusers (no filter)."""
    if user.is_superuser:
        return []
    if user.is_groupadmin or user.is_manager:
        return [UserWorkflows.group_id == user.group_id]
    return [UserWorkflows.user_id == user.user_id]


class DashboardRecentRun(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str
    category_id: int
    category_short_name: str
    type_id: int
    type_long_name: str
    status: str
    started_at: datetime

    class Config:
        from_attributes = True


@router_dashboard.get("/stats", response_model=DashboardStats)
async def get_stats(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    scope = _run_scope_filter(user)

    workflows_count = await session.scalar(
        select(func.count()).select_from(UserWorkflows)
        .where(UserWorkflows.deleted == 0)
        .where(*scope)
    ) or 0

    runs_count = await session.scalar(
        select(func.count()).select_from(WorkflowRuns)
        .join(UserWorkflows)
        .where(
            UserWorkflows.deleted == 0,
            WorkflowRuns.archived.is_(False),
        )
        .where(*scope)
    ) or 0

    runs_today = await session.scalar(
        select(func.count()).select_from(WorkflowRuns)
        .join(UserWorkflows)
        .where(
            UserWorkflows.deleted == 0,
            WorkflowRuns.archived.is_(False),
            func.date(WorkflowRuns.started_at) == func.current_date(),
        )
        .where(*scope)
    ) or 0

    return DashboardStats(
        total_workflows=workflows_count,
        total_runs=runs_count,
        runs_today=runs_today,
        scheduler_running=scheduler.is_running,
    )


@router_dashboard.get("/recent-runs", response_model=list[DashboardRecentRun])
async def recent_runs(
    limit: int = Query(3, ge=1, le=20),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Most-recent N runs visible to the caller under the role-scope rule."""
    scope = _run_scope_filter(user)

    result = await session.execute(
        select(WorkflowRuns, UserWorkflows, WorkflowTypes, WorkflowCategories)
        .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
        .join(WorkflowTypes, WorkflowTypes.type_id == UserWorkflows.type_id)
        .join(WorkflowCategories, WorkflowCategories.category_id == WorkflowTypes.category_id)
        .where(
            UserWorkflows.deleted == 0,
            WorkflowRuns.archived.is_(False),
        )
        .where(*scope)
        .order_by(WorkflowRuns.started_at.desc())
        .limit(limit)
    )

    rows = []
    for run, workflow, wf_type, category in result.all():
        rows.append(
            DashboardRecentRun(
                run_id=run.run_id,
                workflow_id=workflow.workflow_id,
                workflow_name=workflow.name,
                category_id=category.category_id,
                category_short_name=category.short_name,
                type_id=wf_type.type_id,
                type_long_name=wf_type.long_name,
                status=run.status,
                started_at=run.started_at,
            )
        )
    return rows

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
    UserWorkflows,
    WorkflowArtifacts,
    WorkflowCategories,
    WorkflowRuns,
    WorkflowTypes,
)
from backend.db.schemas import DashboardStats
from backend.api.group_context import GroupContext, get_group_context, scope_filter
from backend.services.scheduler_service import scheduler

router_dashboard = APIRouter(prefix="/dashboard")


# The role-scope rule used to live here as _run_scope_filter(user) and keyed
# off the user alone, so a superuser was always system-wide with no way to
# narrow. It now lives in group_context.scope_filter and keys off the acting
# group, letting a superuser see exactly what a member of a chosen group sees.


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
    is_adhoc: bool = False
    # Number of artifacts the run produced. The Dashboard flags a run that
    # completed but wrote nothing — see the same ⚠️ on the Workflows list.
    artifact_count: int = 0

    class Config:
        from_attributes = True


@router_dashboard.get("/stats", response_model=DashboardStats)
async def get_stats(
    ctx: GroupContext = Depends(get_group_context),
    session: AsyncSession = Depends(async_get_session),
):
    scope = scope_filter(ctx)

    # Ad-hoc rows aren't user-managed in the conventional sense — they're
    # fluid per-user state behind the Ad-hoc Workflows menu. Don't count
    # them in "total_workflows".
    workflows_count = await session.scalar(
        select(func.count()).select_from(UserWorkflows)
        .where(UserWorkflows.deleted == 0)
        .where(UserWorkflows.is_adhoc.is_(False))
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
    ctx: GroupContext = Depends(get_group_context),
    session: AsyncSession = Depends(async_get_session),
):
    """Most-recent N runs visible to the caller under the role-scope rule."""
    scope = scope_filter(ctx)

    # Artifact count per run, LEFT JOINed so a run that produced nothing
    # still comes back (as NULL -> 0) rather than dropping out of the list.
    artifact_counts = (
        select(
            WorkflowArtifacts.run_id,
            func.count(WorkflowArtifacts.artifact_id).label("artifact_count"),
        )
        .group_by(WorkflowArtifacts.run_id)
        .subquery()
    )

    result = await session.execute(
        select(
            WorkflowRuns,
            UserWorkflows,
            WorkflowTypes,
            WorkflowCategories,
            artifact_counts.c.artifact_count,
        )
        .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
        .join(WorkflowTypes, WorkflowTypes.type_id == UserWorkflows.type_id)
        .join(WorkflowCategories, WorkflowCategories.category_id == WorkflowTypes.category_id)
        .outerjoin(artifact_counts, artifact_counts.c.run_id == WorkflowRuns.run_id)
        .where(
            UserWorkflows.deleted == 0,
            WorkflowRuns.archived.is_(False),
        )
        .where(*scope)
        .order_by(WorkflowRuns.started_at.desc())
        .limit(limit)
    )

    rows = []
    for run, workflow, wf_type, category, artifact_count in result.all():
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
                is_adhoc=workflow.is_adhoc,
                artifact_count=int(artifact_count or 0),
            )
        )
    return rows

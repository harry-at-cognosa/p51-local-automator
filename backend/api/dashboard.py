from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, UserWorkflows, WorkflowRuns
from backend.db.schemas import DashboardStats
from backend.auth.users import current_active_user

router_dashboard = APIRouter(prefix="/dashboard")


@router_dashboard.get("/stats", response_model=DashboardStats)
async def get_stats(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflows_count = await session.scalar(
        select(func.count()).select_from(UserWorkflows).where(UserWorkflows.group_id == user.group_id)
    ) or 0

    runs_count = await session.scalar(
        select(func.count()).select_from(WorkflowRuns)
        .join(UserWorkflows)
        .where(UserWorkflows.group_id == user.group_id)
    ) or 0

    runs_today = await session.scalar(
        select(func.count()).select_from(WorkflowRuns)
        .join(UserWorkflows)
        .where(
            UserWorkflows.group_id == user.group_id,
            func.date(WorkflowRuns.started_at) == func.current_date(),
        )
    ) or 0

    return DashboardStats(
        total_workflows=workflows_count,
        total_runs=runs_count,
        runs_today=runs_today,
        scheduler_running=False,
    )

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiSettings
from backend.auth.users import current_active_user

router_settings = APIRouter(prefix="/settings")


@router_settings.get("")
async def get_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(select(ApiSettings))
    rows = result.scalars().all()
    return {row.name: row.value for row in rows}


@router_settings.get("/webapp_options")
async def get_webapp_options(
    session: AsyncSession = Depends(async_get_session),
):
    """Public endpoint — returns theme/title settings for the frontend (no auth)."""
    result = await session.execute(select(ApiSettings))
    rows = result.scalars().all()
    settings = {row.name: row.value for row in rows}
    return {
        "app_title": settings.get("app_title", "Local Automator"),
        "navbar_color": settings.get("navbar_color", "slate"),
        "instance_label": settings.get("instance_label", ""),
    }

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiSettings
from backend.auth.users import current_active_user

router_settings = APIRouter(prefix="/settings")


class SettingUpdate(BaseModel):
    value: str


@router_settings.get("")
async def get_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(select(ApiSettings).order_by(ApiSettings.name))
    rows = result.scalars().all()
    return [{"name": row.name, "value": row.value} for row in rows]


@router_settings.put("/{name}")
async def update_setting(
    name: str,
    payload: SettingUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser required")

    setting = await session.get(ApiSettings, name)
    if setting:
        setting.value = payload.value
    else:
        session.add(ApiSettings(name=name, value=payload.value))
    await session.commit()
    return {"name": name, "value": payload.value}


@router_settings.delete("/{name}")
async def delete_setting(
    name: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser required")

    setting = await session.get(ApiSettings, name)
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    await session.delete(setting)
    await session.commit()
    return {"detail": f"Setting '{name}' deleted"}


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
        "sw_version": settings.get("sw_version", ""),
        "db_version": settings.get("db_version", ""),
    }

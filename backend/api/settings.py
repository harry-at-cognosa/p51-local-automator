from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiSettings
from backend.auth.users import current_active_user
from backend.services.path_validator import validate_root_path

router_settings = APIRouter(prefix="/settings")


class SettingUpdate(BaseModel):
    value: str


class PathValidateRequest(BaseModel):
    path: str


class PathValidateResponse(BaseModel):
    ok: bool
    path: str
    reason: str
    exists: bool
    is_dir: bool
    writable: bool


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


@router_settings.post("/validate-path", response_model=PathValidateResponse)
async def validate_path(
    payload: PathValidateRequest,
    user: User = Depends(current_active_user),
):
    """Probe a filesystem path for the Settings UI Test button.

    Allowed to groupadmin+ (groupadmins need to test their group's
    file_system_root before saving). The probe writes and removes a
    tempfile to verify true writability.
    """
    if not (user.is_groupadmin or user.is_superuser):
        raise HTTPException(status_code=403, detail="Group admin or superuser required")
    result = validate_root_path(payload.path)
    return PathValidateResponse(
        ok=result.ok,
        path=result.path,
        reason=result.reason,
        exists=result.exists,
        is_dir=result.is_dir,
        writable=result.writable,
    )


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
        "trim_color": settings.get("trim_color", ""),
        "instance_label": settings.get("instance_label", ""),
        "sw_version": settings.get("sw_version", ""),
        "db_version": settings.get("db_version", ""),
    }

"""Group settings API — per-group key/value config for groupadmin+."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, GroupSettings
from backend.auth.users import current_active_user

router_group_settings = APIRouter(prefix="/group-settings")


class GroupSettingOut(BaseModel):
    name: str
    value: str

    class Config:
        from_attributes = True


class GroupSettingUpdate(BaseModel):
    value: str


def _require_groupadmin(user: User):
    if not (user.is_groupadmin or user.is_superuser):
        raise HTTPException(status_code=403, detail="Group admin required")


@router_group_settings.get("", response_model=list[GroupSettingOut])
async def list_group_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_groupadmin(user)
    result = await session.execute(
        select(GroupSettings)
        .where(GroupSettings.group_id == user.group_id)
        .order_by(GroupSettings.name)
    )
    return result.scalars().all()


@router_group_settings.put("/{name}", response_model=GroupSettingOut)
async def upsert_group_setting(
    name: str,
    payload: GroupSettingUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_groupadmin(user)
    result = await session.execute(
        select(GroupSettings).where(
            GroupSettings.group_id == user.group_id,
            GroupSettings.name == name,
        )
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = payload.value
    else:
        session.add(GroupSettings(group_id=user.group_id, name=name, value=payload.value))
    await session.commit()
    return GroupSettingOut(name=name, value=payload.value)


@router_group_settings.delete("/{name}")
async def delete_group_setting(
    name: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_groupadmin(user)
    result = await session.execute(
        select(GroupSettings).where(
            GroupSettings.group_id == user.group_id,
            GroupSettings.name == name,
        )
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    await session.delete(setting)
    await session.commit()
    return {"detail": f"Group setting '{name}' deleted"}

"""Group management API for superusers."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiGroups
from backend.auth.users import current_active_user

router_manage_groups = APIRouter()


class GroupRead(BaseModel):
    group_id: int
    group_name: str
    is_active: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class GroupCreate(BaseModel):
    group_name: str


class GroupUpdate(BaseModel):
    group_name: str | None = None
    is_active: bool | None = None


def _require_superuser(user: User):
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser required")


@router_manage_groups.get("/manage/groups", response_model=list[GroupRead])
async def list_groups(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_superuser(user)
    result = await session.execute(
        select(ApiGroups).where(ApiGroups.deleted == 0).order_by(ApiGroups.group_id)
    )
    return result.scalars().all()


@router_manage_groups.post("/manage/groups", response_model=GroupRead, status_code=201)
async def create_group(
    payload: GroupCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_superuser(user)
    group = ApiGroups(group_name=payload.group_name)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


@router_manage_groups.put("/manage/groups/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: int,
    payload: GroupUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_superuser(user)
    group = await session.get(ApiGroups, group_id)
    if not group or group.deleted != 0:
        raise HTTPException(status_code=404, detail="Group not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)

    await session.commit()
    await session.refresh(group)
    return group

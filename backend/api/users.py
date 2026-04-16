from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiGroups
from backend.db.schemas import UsersMe
from backend.auth.users import current_active_user

router_users = APIRouter()


@router_users.get("/users/me", response_model=UsersMe)
async def get_me(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(
        select(ApiGroups.group_name).where(ApiGroups.group_id == user.group_id)
    )
    group_name = result.scalar_one_or_none() or "Unknown"

    return UsersMe(
        id=user.id,
        user_id=user.user_id,
        group_id=user.group_id,
        group_name=group_name,
        email=user.email,
        user_name=user.user_name,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        is_groupadmin=user.is_groupadmin,
        is_manager=user.is_manager,
    )

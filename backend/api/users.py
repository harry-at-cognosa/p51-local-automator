from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, ApiGroups
from backend.db.schemas import UsersMe, UsersMePatch
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
        outbound_service=user.outbound_service,
        outbound_identifier=user.outbound_identifier,
    )


@router_users.patch("/users/me", response_model=UsersMe)
async def patch_me(
    payload: UsersMePatch,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Update the current user's outbound-email preferences.

    Field semantics:
      - outbound_service=None: clears designation (also nulls identifier).
      - outbound_service='gmail_imap' with outbound_app_password set: also
        writes the password to .gmailpasswords.json keyed by the identifier
        (the consumer Gmail email address). Blank app_password leaves any
        existing stored value untouched (masked-secret UX).
    """
    user.outbound_service = payload.outbound_service
    if payload.outbound_service is None:
        user.outbound_identifier = None
    elif payload.outbound_identifier is not None:
        user.outbound_identifier = (payload.outbound_identifier or "").strip() or None

    # Side-effect: write App Password for gmail_imap to the machine-wide
    # .gmailpasswords.json (only if the client sent a non-empty value).
    if (
        payload.outbound_service == "gmail_imap"
        and payload.outbound_app_password
        and user.outbound_identifier
    ):
        from backend.services.gmail_password_store import _load_file_locked, _write_file_locked, _strip
        data = _load_file_locked()
        data[user.outbound_identifier] = _strip(payload.outbound_app_password)
        _write_file_locked(data)

    await session.flush()
    await session.commit()
    await session.refresh(user)

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
        outbound_service=user.outbound_service,
        outbound_identifier=user.outbound_identifier,
    )

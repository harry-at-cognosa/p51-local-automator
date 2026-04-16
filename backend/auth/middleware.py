from datetime import datetime, timezone, timedelta

from fastapi import Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User
from backend.auth.users import current_active_user_or_none

LAST_SEEN_MIN_DELTA = timedelta(seconds=60)


async def refresh_last_seen(
    user: User = Depends(current_active_user_or_none),
    session: AsyncSession = Depends(async_get_session),
) -> None:
    if not user:
        return
    try:
        now = datetime.now(timezone.utc)
        last_seen = getattr(user, "last_seen", None)
        if last_seen is not None:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if (now - last_seen) < LAST_SEEN_MIN_DELTA:
                return
        await session.execute(
            update(User).where(User.user_id == user.user_id).values(last_seen=now)
        )
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass

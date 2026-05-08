"""Google Calendar API surface (Track GC).

Endpoints:
    GET /google-calendar/calendars?account_id=N
        → list calendars the connected Google account has access to
          (used by the Type 3 form's calendar multi-select picker)

The actual events.list calls happen inside the calendar_digest runner;
this router only exposes data the form needs to build its config.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.db.models import GmailAccounts, User
from backend.db.session import async_get_session
from backend.services import google_calendar_client


router_google_calendar = APIRouter(prefix="/google-calendar")


@router_google_calendar.get("/calendars")
async def list_calendars(
    account_id: int = Query(..., description="GmailAccounts.id of the Google account to query"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """List calendars accessible to the given Google account.

    Caller must own the account (gmail_accounts.user_id == current_user)
    so one user can't enumerate another user's calendars by guessing
    account ids."""
    account = await session.get(GmailAccounts, account_id)
    if not account or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        return await google_calendar_client.calendar_list_calendars(
            session, account_id=account_id
        )
    except RuntimeError as e:
        # Most common: scope not granted yet (account predates GC.1).
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendar API error: {str(e)[:200]}")

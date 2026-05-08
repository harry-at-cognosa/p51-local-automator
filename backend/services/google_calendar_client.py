"""Read-only Google Calendar API client (Track GC).

Parallels backend/services/gmail_client.py — same auth pattern, same
account loading, same usage logging. Calendar functions:

    calendar_list_calendars(session, account_id) -> [{id, summary, primary, ...}, ...]
    calendar_list_events(session, account_id, calendar_ids, time_min, time_max)
        -> [{summary, startDate, endDate, location, calendar, ...}, ...]

Returned event dicts deliberately mirror the Apple Calendar MCP shape
(`startDate`, `endDate`, `summary`, `location`, `calendar`) so the digest
engine can branch on `service` with minimal divergence in downstream
formatting code.

Storage reuse: gmail_accounts holds OAuth credentials for all per-Google-
account services (Gmail and now Calendar). The account's `scopes` column
must include `https://www.googleapis.com/auth/calendar.readonly`; if it
doesn't, calls raise RuntimeError pointing the user at /app/connections
to re-consent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import GmailAccounts
from backend.services.gmail_client import (
    GmailAccountNotActiveError,
    _build_service as _build_gmail_service,  # not used here, kept for future read of API patterns
    _ensure_fresh_credentials,
    _load_active_account,
    _log_event,
)
from backend.services.logger_service import get_logger


log = get_logger("google_calendar_client")


CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _require_calendar_scope(account: GmailAccounts) -> None:
    """Refuse calls if the account doesn't carry calendar.readonly."""
    granted = (account.scopes or "").split()
    if CALENDAR_SCOPE not in granted:
        raise RuntimeError(
            f"Account {account.email} lacks calendar.readonly scope. "
            f"Reconnect via /app/connections to grant calendar access."
        )


def _build_calendar_service(creds):
    """Lazy-build the Calendar v3 service object."""
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _normalize_event(ev: dict[str, Any], calendar_label: str) -> dict[str, Any]:
    """Map a Google Calendar event into the Apple-MCP-compatible dict shape.

    All-day events have `start.date` (no time); timed events have
    `start.dateTime`. Both surface as ISO 8601 strings in `startDate`
    so downstream code can sort lexicographically.
    """
    start = ev.get("start", {}) or {}
    end = ev.get("end", {}) or {}
    return {
        "id": ev.get("id", ""),
        "summary": ev.get("summary") or "(no title)",
        "startDate": start.get("dateTime") or start.get("date") or "",
        "endDate": end.get("dateTime") or end.get("date") or "",
        "location": ev.get("location") or "",
        "calendar": calendar_label,
        "html_link": ev.get("htmlLink", ""),
        "organizer": (ev.get("organizer") or {}).get("email", ""),
    }


async def calendar_list_calendars(
    session: AsyncSession,
    account_id: int,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """List calendars the account has access to. Used by the form's
    multi-select picker. Returns one dict per calendar:
      {id, summary, primary, access_role, color}
    """
    account = await _load_active_account(session, account_id)
    _require_calendar_scope(account)
    creds = await _ensure_fresh_credentials(session, account)

    def _list():
        service = _build_calendar_service(creds)
        items = service.calendarList().list().execute().get("items", []) or []
        return [
            {
                "id": c.get("id", ""),
                "summary": c.get("summaryOverride") or c.get("summary", ""),
                "primary": bool(c.get("primary")),
                "access_role": c.get("accessRole", ""),
                "color": c.get("backgroundColor", ""),
            }
            for c in items
        ]

    try:
        out = await asyncio.to_thread(_list)
    except Exception as e:
        await _log_event(session, account_id, "calendar_list_calendars",
                         workflow_id, run_id, str(e)[:500])
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "calendar_list_calendars", workflow_id, run_id)
    await session.flush()
    return out


async def calendar_list_events(
    session: AsyncSession,
    account_id: int,
    calendar_ids: list[str],
    time_min: datetime,
    time_max: datetime,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch events from one or more calendars within the time window.

    Google's events.list takes one calendarId at a time; we loop and
    union the results. Each event is normalized to the Apple-MCP-style
    dict shape so the digest engine can treat both services identically.

    `time_min` / `time_max` are ISO-formatted with timezone before being
    sent to Google. Naive datetimes are assumed UTC.
    """
    account = await _load_active_account(session, account_id)
    _require_calendar_scope(account)
    creds = await _ensure_fresh_credentials(session, account)

    if time_min.tzinfo is None:
        time_min = time_min.replace(tzinfo=timezone.utc)
    if time_max.tzinfo is None:
        time_max = time_max.replace(tzinfo=timezone.utc)
    tmin = time_min.isoformat()
    tmax = time_max.isoformat()

    # Pre-fetch the calendarList once so we can label each event with its
    # calendar's display name (Google's events.list returns calendar id but
    # not the human-friendly summary).
    cal_summaries = {c["id"]: c["summary"] for c in await calendar_list_calendars(
        session, account_id, workflow_id=workflow_id, run_id=run_id
    )}

    def _list_one(cal_id: str) -> list[dict[str, Any]]:
        service = _build_calendar_service(creds)
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "calendarId": cal_id,
                "timeMin": tmin,
                "timeMax": tmax,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = service.events().list(**params).execute()
            for ev in resp.get("items", []) or []:
                out.append(_normalize_event(ev, cal_summaries.get(cal_id, cal_id)))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out

    try:
        results: list[dict[str, Any]] = []
        for cid in calendar_ids:
            results.extend(await asyncio.to_thread(_list_one, cid))
    except Exception as e:
        await _log_event(session, account_id, "calendar_list_events",
                         workflow_id, run_id, str(e)[:500])
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "calendar_list_events", workflow_id, run_id)
    await session.flush()
    return results

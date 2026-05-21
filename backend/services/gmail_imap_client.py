"""IMAP client for consumer Gmail using App Passwords.

Distinct from `backend/services/gmail_client.py`, which is the OAuth +
Gmail API path used by the regular Type 1 workflows. This module is
used exclusively by the new "Ad-hoc Email Topic Monitor" path
(service value "gmail_imap" in workflow.config.accounts).

Why a separate path:
  - Consumer Gmail under p51's current Testing-mode OAuth client has
    refresh tokens that expire every 7 days, which kills daily-run
    scenarios. App Passwords have no equivalent expiration.
  - App Passwords sidestep the 100-user CASA testing-mode cap entirely
    — that cap applies to API access, not IMAP login.
  - The user generates a 16-char app password at myaccount.google.com
    (requires 2FA) and pastes it into the form; we use it as plain
    IMAP credentials.

Functions:
  - imap_test_login(email, app_password) → (ok: bool, reason: str)
  - imap_list_messages(email, app_password, mailbox, since_dt, limit)
        → list[dict] with id/sender/subject/date/snippet keys, matching
        the shape gmail_client.gmail_list_messages emits so the runner
        dispatch can swap cleanly.

imaplib is the stdlib choice — no new dependency. It's synchronous; we
run it under asyncio.to_thread() so the FastAPI event loop isn't blocked.
"""
from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
import logging
from datetime import datetime, timezone
from email.header import decode_header

from backend.services.logger_service import get_logger

log = get_logger("gmail_imap_client")

_GMAIL_IMAP_HOST = "imap.gmail.com"
_GMAIL_IMAP_PORT = 993
_LOGIN_TIMEOUT_SECONDS = 10


def _decode_header_field(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except Exception:
        return raw
    decoded: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                decoded.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


def _strip_app_password(s: str) -> str:
    """Google displays app passwords as `xxxx xxxx xxxx xxxx`; strip
    every whitespace character so a paste of the spaced form works."""
    return "".join(s.split())


def _sync_test_login(email_addr: str, app_password: str) -> tuple[bool, str]:
    """Sync helper — run under asyncio.to_thread."""
    pw = _strip_app_password(app_password)
    if len(pw) != 16:
        return False, (
            f"App password should be 16 characters (got {len(pw)} after "
            "stripping whitespace). Generate one at "
            "myaccount.google.com/apppasswords."
        )
    try:
        with imaplib.IMAP4_SSL(_GMAIL_IMAP_HOST, _GMAIL_IMAP_PORT, timeout=_LOGIN_TIMEOUT_SECONDS) as m:
            m.login(email_addr, pw)
            return True, "ok"
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "AUTHENTICATIONFAILED" in msg.upper():
            return False, "AUTHENTICATIONFAILED — bad email/app-password combination."
        return False, msg
    except OSError as e:
        return False, f"Network/connection error: {e}"
    except Exception as e:  # pragma: no cover — defensive
        return False, f"Unexpected error: {e}"


async def imap_test_login(email_addr: str, app_password: str) -> tuple[bool, str]:
    """Return (ok, reason). Used by the /ad-hoc/.../test endpoint to
    validate credentials without actually fetching messages."""
    return await asyncio.to_thread(_sync_test_login, email_addr, app_password)


def _sync_list_messages(
    email_addr: str,
    app_password: str,
    mailbox: str,
    since_dt: datetime,
    limit: int,
) -> list[dict]:
    pw = _strip_app_password(app_password)
    since_str = since_dt.strftime("%d-%b-%Y")  # IMAP SINCE wants DD-MMM-YYYY
    results: list[dict] = []
    with imaplib.IMAP4_SSL(_GMAIL_IMAP_HOST, _GMAIL_IMAP_PORT, timeout=_LOGIN_TIMEOUT_SECONDS) as m:
        m.login(email_addr, pw)
        # Gmail allows imap_select on label folders ("[Gmail]/All Mail") or
        # the literal INBOX. Pass the user-supplied mailbox through as-is.
        status, _ = m.select(mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"IMAP SELECT {mailbox!r} failed: {status}")
        status, data = m.search(None, f'(SINCE "{since_str}")')
        if status != "OK":
            raise RuntimeError(f"IMAP SEARCH failed: {status}")
        ids = data[0].split() if data and data[0] else []
        # Newest first — IMAP returns ascending order.
        ids = list(reversed(ids))[:limit]
        for msg_id in ids:
            status, msg_data = m.fetch(msg_id, "(BODY.PEEK[HEADER])")
            if status != "OK" or not msg_data:
                continue
            # imaplib returns a list of tuples and a closing b')'; pull the
            # first tuple's second element which is the raw header bytes.
            raw = None
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2:
                    raw = part[1]
                    break
            if raw is None:
                continue
            parsed = email.message_from_bytes(raw)
            date_str = parsed.get("Date", "")
            try:
                date_tuple = email.utils.parsedate_to_datetime(date_str)
                if date_tuple and date_tuple.tzinfo is None:
                    date_tuple = date_tuple.replace(tzinfo=timezone.utc)
            except Exception:
                date_tuple = None
            results.append({
                "id": msg_id.decode("ascii", errors="replace"),
                "sender": _decode_header_field(parsed.get("From", "")),
                "subject": _decode_header_field(parsed.get("Subject", "")),
                "date": date_tuple.isoformat() if date_tuple else date_str,
                "snippet": "",  # IMAP doesn't have Gmail-style snippets cheaply
            })
    return results


async def imap_list_messages(
    email_addr: str,
    app_password: str,
    mailbox: str,
    since_dt: datetime,
    limit: int = 50,
) -> list[dict]:
    """List recent messages from Gmail via IMAP. Mirrors the read-side
    surface of gmail_client.gmail_list_messages so the email_monitor
    runner can dispatch by service.

    Returns a list of dicts with id, sender, subject, date, snippet.
    Snippet is empty — IMAP doesn't have Gmail's cheap snippet
    extraction; fetching bodies for previews is deferred until the
    runner actually needs them.
    """
    return await asyncio.to_thread(
        _sync_list_messages, email_addr, app_password, mailbox, since_dt, limit
    )

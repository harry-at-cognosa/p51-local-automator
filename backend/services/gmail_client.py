"""Read-only Gmail API client (Track B Phase B1).

Parallels backend/services/mcp_client.py's apple_mail surface:

    gmail_list_messages(session, account_id, mailbox="INBOX", limit=50, ...)
    gmail_get_message(session, account_id, message_id, ...)
    gmail_search(session, account_id, query, limit=25, ...)

Each function:
1. Loads the GmailAccount row by id; refuses if status != 'active'.
2. Builds a google.oauth2.credentials.Credentials from decrypted tokens.
3. Calls Gmail API. The credentials object lazy-refreshes the access token
   using the stored refresh token if it's expired or revoked-and-still-
   refreshable; we re-encrypt and persist the new access token.
4. If the refresh itself fails (refresh token revoked at Google's side),
   the account is flipped to status='disconnected' and the function raises.
5. Writes a gmail_token_usage row tagged with the action and any error.

Returned dict shapes deliberately mirror mcp_client's apple_mail output so
downstream code paths (email_monitor, etc.) can branch on `service` with
minimal divergence:

    {"id": str, "sender": str, "subject": str, "date": str, ...}

`date` is an ISO 8601 string with timezone (parsed from the RFC 2822
Date header by gmail).
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from backend.db.models import GmailAccounts, GmailTokenUsage
from backend.services import secrets as crypto
from backend.services.logger_service import get_logger


log = get_logger("gmail_client")


class GmailAccountNotActiveError(RuntimeError):
    """Raised when a caller targets a Gmail account that's disconnected or revoked."""


class GmailRefreshFailedError(RuntimeError):
    """Raised when refreshing the access token fails (refresh token revoked)."""


def _build_credentials(account: GmailAccounts):
    """Construct a google.oauth2.credentials.Credentials from a GmailAccount row.

    Lazy import — google modules pull in a chunk of dependencies.
    """
    from google.oauth2.credentials import Credentials

    refresh_token = crypto.decrypt(account.refresh_token_encrypted)
    access_token = (
        crypto.decrypt(account.access_token_encrypted)
        if account.access_token_encrypted
        else None
    )
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=account.scopes.split() if account.scopes else None,
    )


async def _ensure_fresh_credentials(
    session: AsyncSession,
    account: GmailAccounts,
):
    """Return a Credentials object guaranteed to have a non-expired access token.

    If the stored access token is missing or expired, refreshes via the
    refresh token and persists the new access token (encrypted) and expiry
    back to the row. If the refresh itself fails, marks the account
    disconnected and raises GmailRefreshFailedError.
    """
    creds = _build_credentials(account)
    if creds.valid:
        return creds

    # Run the (synchronous) refresh in a thread so we don't block the loop.
    def _refresh():
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    try:
        await asyncio.to_thread(_refresh)
    except Exception as e:
        log.warning("gmail_token_refresh_failed", account_id=account.id, error=str(e)[:200])
        account.status = "disconnected"
        await session.flush()
        raise GmailRefreshFailedError(
            f"Could not refresh access token for {account.email}: {e}"
        ) from e

    # Persist the new access token + expiry.
    account.access_token_encrypted = crypto.encrypt(creds.token)
    expiry = creds.expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    account.access_token_expires_at = expiry
    await session.flush()
    return creds


async def _log_event(
    session: AsyncSession,
    account_id: int,
    action: str,
    workflow_id: int | None,
    run_id: int | None,
    error_detail: str | None = None,
):
    session.add(
        GmailTokenUsage(
            account_id=account_id,
            workflow_id=workflow_id,
            run_id=run_id,
            action=action,
            error_detail=error_detail,
        )
    )
    await session.flush()


async def _load_active_account(session: AsyncSession, account_id: int) -> GmailAccounts:
    account = await session.get(GmailAccounts, account_id)
    if not account:
        raise GmailAccountNotActiveError(f"Gmail account #{account_id} not found.")
    if account.status != "active":
        raise GmailAccountNotActiveError(
            f"Gmail account {account.email} is {account.status}; reconnect via /app/connections."
        )
    return account


def _header(headers: list[dict[str, str]], name: str) -> str:
    """Return the value of an RFC 2822 header from Gmail's header list, or ''."""
    needle = name.lower()
    for h in headers:
        if h.get("name", "").lower() == needle:
            return h.get("value", "")
    return ""


def _normalize_date(rfc2822: str) -> str:
    """Convert a Gmail Date header to ISO 8601 with timezone, or pass through."""
    if not rfc2822:
        return ""
    try:
        dt = parsedate_to_datetime(rfc2822)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return rfc2822


def _summarize_message_metadata(msg: dict[str, Any]) -> dict[str, str]:
    """Extract id/sender/subject/date from a Gmail messages.get(format=metadata) response."""
    headers = msg.get("payload", {}).get("headers", []) or []
    return {
        "id": msg.get("id", ""),
        "sender": _header(headers, "From"),
        "subject": _header(headers, "Subject"),
        "date": _normalize_date(_header(headers, "Date")),
    }


def _decode_part_body(part: dict[str, Any]) -> str:
    """Decode a single MIME part's body, if it has data."""
    body = part.get("body") or {}
    data = body.get("data")
    if not data:
        return ""
    # Gmail uses URL-safe base64 without padding.
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Walk the MIME tree, prefer text/plain over text/html."""
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode_part_body(payload)
    parts = payload.get("parts") or []
    # Prefer plain
    for p in parts:
        if p.get("mimeType") == "text/plain":
            text = _decode_part_body(p)
            if text:
                return text
    # Fall back to html
    for p in parts:
        if p.get("mimeType") == "text/html":
            text = _decode_part_body(p)
            if text:
                return text
    # Recurse into multipart/* nodes
    for p in parts:
        if p.get("mimeType", "").startswith("multipart/"):
            text = _extract_body(p)
            if text:
                return text
    # Top-level html only
    if mime == "text/html":
        return _decode_part_body(payload)
    return ""


def _build_service(creds):
    """Lazy import + build the Gmail API service object."""
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def gmail_list_messages(
    session: AsyncSession,
    account_id: int,
    mailbox: str = "INBOX",
    limit: int = 50,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[dict[str, str]]:
    """List messages with id/sender/subject/date for the given mailbox label.

    `mailbox` maps to a Gmail label id (INBOX, SPAM, TRASH, or any custom
    label the user has). Returns up to `limit` messages.
    """
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)

    def _list_and_metadata():
        service = _build_service(creds)
        listed = service.users().messages().list(
            userId="me", labelIds=[mailbox], maxResults=limit,
        ).execute()
        ids = [m["id"] for m in (listed.get("messages") or [])]
        out: list[dict[str, str]] = []
        for mid in ids:
            msg = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            out.append(_summarize_message_metadata(msg))
        return out

    try:
        results = await asyncio.to_thread(_list_and_metadata)
    except Exception as e:
        await _log_event(session, account_id, "list_messages", workflow_id, run_id, str(e)[:500])
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "list_messages", workflow_id, run_id)
    await session.flush()
    return results


async def gmail_get_message(
    session: AsyncSession,
    account_id: int,
    message_id: str,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> dict[str, Any]:
    """Fetch a single message with full body."""
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)

    def _get():
        service = _build_service(creds)
        return service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()

    try:
        msg = await asyncio.to_thread(_get)
    except Exception as e:
        await _log_event(session, account_id, "get_message", workflow_id, run_id, str(e)[:500])
        raise

    payload = msg.get("payload", {}) or {}
    headers = payload.get("headers", []) or []
    out = {
        "id": msg.get("id", ""),
        "sender": _header(headers, "From"),
        "subject": _header(headers, "Subject"),
        "date": _normalize_date(_header(headers, "Date")),
        "to": _header(headers, "To"),
        "reply_to": _header(headers, "Reply-To"),
        "body": _extract_body(payload),
        "snippet": msg.get("snippet", ""),
    }

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "get_message", workflow_id, run_id)
    await session.flush()
    return out


async def gmail_search(
    session: AsyncSession,
    account_id: int,
    query: str,
    limit: int = 25,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[dict[str, str]]:
    """Search via Gmail's q= syntax (e.g. 'from:foo@bar.com newer_than:7d')."""
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)

    def _search():
        service = _build_service(creds)
        listed = service.users().messages().list(
            userId="me", q=query, maxResults=limit,
        ).execute()
        ids = [m["id"] for m in (listed.get("messages") or [])]
        out: list[dict[str, str]] = []
        for mid in ids:
            msg = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            out.append(_summarize_message_metadata(msg))
        return out

    try:
        results = await asyncio.to_thread(_search)
    except Exception as e:
        await _log_event(session, account_id, "search", workflow_id, run_id, str(e)[:500])
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "search", workflow_id, run_id)
    await session.flush()
    return results

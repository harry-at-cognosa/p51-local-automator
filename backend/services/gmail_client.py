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


def _looks_like_invalid_grant(exc: Exception) -> bool:
    """True when an exception almost certainly means the OAuth refresh
    token is dead (expired/revoked at Google) — either because the
    explicit refresh failed or because the api-client's auto-refresh
    during an API call failed.

    We treat the following as positive signals:
      - google.auth.exceptions.RefreshError (any subclass)
      - any exception whose stringified form contains "invalid_grant"
      - any exception mentioning "Token has been expired or revoked"
    """
    try:
        from google.auth.exceptions import RefreshError
        if isinstance(exc, RefreshError):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return "invalid_grant" in msg or "expired or revoked" in msg


async def _flip_disconnected_if_refresh_failure(
    session: AsyncSession,
    account: GmailAccounts,
    exc: Exception,
) -> bool:
    """If `exc` looks like an OAuth refresh failure, set the account's
    status to 'disconnected' and flush. Returns True when flipped, False
    otherwise. Caller is responsible for re-raising.

    The caller's request handler must commit the session for the change
    to survive; the standard FastAPI dependency closes the session
    without commit on its own, which would roll back this flush.
    """
    if not _looks_like_invalid_grant(exc):
        return False
    if account.status != "disconnected":
        log.warning(
            "gmail_account_marked_disconnected",
            account_id=account.id, error=str(exc)[:200],
        )
        account.status = "disconnected"
        await session.flush()
    return True


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
        await _flip_disconnected_if_refresh_failure(session, account, e)
        # Even if the exception wasn't an obvious invalid_grant, the refresh
        # failed — preserve the historical behavior of marking the account
        # disconnected so retries don't loop.
        if account.status != "disconnected":
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
        await _flip_disconnected_if_refresh_failure(session, account, e)
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
        await _flip_disconnected_if_refresh_failure(session, account, e)
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


def _build_mime_message(
    *,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    attachments: list[str] | None = None,
) -> str:
    """Construct an RFC 822 message and return its base64url-encoded raw form,
    ready for Gmail's drafts.create / messages.send.

    `in_reply_to` is the source message's RFC 822 Message-ID header value
    (with brackets, e.g. `<abc@mail.gmail.com>`); when supplied it's also
    written to References so Gmail threads the reply with the original.

    `attachments` is a list of absolute filesystem paths. When non-empty the
    resulting message is multipart; EmailMessage.add_attachment() handles
    the MIME composition. MIME type is guessed from the filename via the
    stdlib `mimetypes` module, falling back to application/octet-stream.
    """
    import mimetypes
    from email.message import EmailMessage
    from pathlib import Path

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    for path_str in attachments or []:
        p = Path(path_str)
        if not p.is_file():
            log.warning("gmail_attachment_missing", path=str(p))
            continue
        guessed, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (guessed or "application/octet-stream").split("/", 1)
        with p.open("rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)

    raw_bytes = msg.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


async def gmail_save_draft(
    session: AsyncSession,
    account_id: int,
    *,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> dict[str, str]:
    """Create a Gmail draft. Returns {'id', 'message_id', 'thread_id'}.

    Requires the gmail.compose scope (added in B2.1)."""
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)
    raw = _build_mime_message(to=to, subject=subject, body=body, in_reply_to=in_reply_to)

    def _create():
        service = _build_service(creds)
        return service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

    try:
        result = await asyncio.to_thread(_create)
    except Exception as e:
        await _log_event(session, account_id, "save_draft", workflow_id, run_id, str(e)[:500])
        await _flip_disconnected_if_refresh_failure(session, account, e)
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "save_draft", workflow_id, run_id)
    await session.flush()
    inner = result.get("message") or {}
    return {
        "id": result.get("id", ""),
        "message_id": inner.get("id", ""),
        "thread_id": inner.get("threadId", ""),
    }


async def gmail_send_message(
    session: AsyncSession,
    account_id: int,
    *,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    attachments: list[str] | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> dict[str, str]:
    """Send a Gmail message via users.messages.send. Returns
    {'message_id', 'thread_id'}.

    Requires the gmail.send scope (added in B2.1). `attachments` is an
    optional list of absolute paths to files to attach."""
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)
    raw = _build_mime_message(
        to=to,
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        attachments=attachments,
    )

    def _send():
        service = _build_service(creds)
        return service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

    try:
        result = await asyncio.to_thread(_send)
    except Exception as e:
        await _log_event(session, account_id, "send_message", workflow_id, run_id, str(e)[:500])
        await _flip_disconnected_if_refresh_failure(session, account, e)
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "send_message", workflow_id, run_id)
    await session.flush()
    return {
        "message_id": result.get("id", ""),
        "thread_id": result.get("threadId", ""),
    }


GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def _account_has_modify_scope(account: GmailAccounts) -> bool:
    """True when the account's granted scopes include gmail.modify.

    Trashing a message requires gmail.modify; accounts connected before the
    scope was added to SCOPES will lack it and must reconnect (re-consent).
    """
    granted = (account.scopes or "").split()
    return GMAIL_MODIFY_SCOPE in granted


async def gmail_search_senders_before(
    session: AsyncSession,
    account_id: int,
    from_address: str,
    before_date: str,
    limit: int = 500,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[dict[str, str]]:
    """Find messages from `from_address` dated strictly before `before_date`.

    `before_date` is a Gmail-style date string ``YYYY/MM/DD``. No labelIds are
    applied, so the search spans All Mail (including archived) — matching the
    Email Reaper "all mail" scan scope. Returns id/sender/subject/date dicts.
    """
    query = f"from:{from_address} before:{before_date}"
    return await gmail_search(
        session, account_id, query, limit=limit,
        workflow_id=workflow_id, run_id=run_id,
    )


async def gmail_trash_messages(
    session: AsyncSession,
    account_id: int,
    message_ids: list[str],
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> list[str]:
    """Move the given messages to Trash via users.messages.trash.

    Recoverable (Gmail retains trashed mail ~30 days). Requires the
    gmail.modify scope. Per-message failures are logged and skipped; returns
    the list of ids successfully trashed.
    """
    account = await _load_active_account(session, account_id)
    creds = await _ensure_fresh_credentials(session, account)

    def _trash_all():
        service = _build_service(creds)
        trashed: list[str] = []
        for mid in message_ids:
            try:
                service.users().messages().trash(userId="me", id=mid).execute()
                trashed.append(mid)
            except Exception as e:  # noqa: BLE001 - degrade per message
                log.warning("gmail_trash_message_failed", account_id=account_id,
                            message_id=mid, error=str(e)[:200])
        return trashed

    try:
        trashed = await asyncio.to_thread(_trash_all)
    except Exception as e:
        await _log_event(session, account_id, "trash_messages", workflow_id, run_id, str(e)[:500])
        await _flip_disconnected_if_refresh_failure(session, account, e)
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "trash_messages", workflow_id, run_id)
    await session.flush()
    return trashed


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
        await _flip_disconnected_if_refresh_failure(session, account, e)
        raise

    account.last_used_at = datetime.now(timezone.utc)
    await _log_event(session, account_id, "search", workflow_id, run_id)
    await session.flush()
    return results

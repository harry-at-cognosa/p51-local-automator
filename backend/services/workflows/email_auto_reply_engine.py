"""Shared engine for email auto-reply workflows.

Two runners (email_auto_reply_draft, email_auto_reply_approve) both call into
this module. It handles:
  - Fetching recent messages via Apple Mail MCP
  - Filtering candidates by sender and body-substring criteria
  - Skipping already-handled messages via email_auto_reply_log
  - Pulling full body + reply-to from each candidate
  - Generating the reply text with Claude

The terminal action (save to Drafts, or insert into pending_email_replies,
or send directly) is the caller's responsibility.
"""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import EmailAutoReplyLog, UserWorkflows
from backend.services import llm_service, mcp_client
from backend.services.logger_service import get_logger

log = get_logger("email_auto_reply")


@dataclass
class ReplyCandidate:
    """A matched inbound email with its generated reply draft."""
    source_message_id: str
    source_account: str
    source_mailbox: str
    source_from: str        # raw sender header
    source_subject: str
    source_body: str        # full body text
    to_address: str         # extracted reply-to (or fallback to sender email)
    reply_subject: str      # LLM-generated "Re: ..."
    reply_body: str         # LLM-generated body (with signature if configured)
    llm_tokens: int


_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")


def _extract_email(raw: str) -> str:
    """Pick the email address out of a 'Name <addr>' or 'addr' string."""
    if not raw:
        return ""
    m = _EMAIL_RE.search(raw)
    return m.group(0) if m else raw.strip()


def _matches_filters(msg: dict, body: str, sender_filter: str, body_contains: str) -> bool:
    """Return True if this message is a candidate for acknowledgment."""
    sender = (msg.get("sender") or "") + " " + (msg.get("from") or "")
    if sender_filter and sender_filter.lower() not in sender.lower():
        return False
    if body_contains and body_contains.lower() not in body.lower():
        return False
    # Require SOMETHING to avoid an empty-filter run nuking the inbox.
    if not sender_filter and not body_contains:
        return False
    return True


def _pick_reply_to(full_msg: dict, source_from: str) -> str:
    """Prefer the Reply-To header if present; fall back to the sender."""
    reply_to_raw = full_msg.get("reply_to") or full_msg.get("replyTo") or ""
    address = _extract_email(reply_to_raw) if reply_to_raw else ""
    if not address:
        address = _extract_email(source_from)
    return address


async def _already_handled_ids(
    session: AsyncSession, workflow_id: int, message_ids: list[str]
) -> set[str]:
    """Return the subset of `message_ids` already present in the dedup log."""
    if not message_ids:
        return set()
    result = await session.execute(
        select(EmailAutoReplyLog.source_message_id)
        .where(EmailAutoReplyLog.workflow_id == workflow_id)
        .where(EmailAutoReplyLog.source_message_id.in_(message_ids))
    )
    return {row[0] for row in result.all()}


async def find_and_generate_candidates(
    session: AsyncSession,
    workflow: UserWorkflows,
    max_candidates: int = 20,
) -> list[ReplyCandidate]:
    """Run Step 1+2+3 of either auto-reply runner: fetch, filter, LLM-draft.

    Returns zero or more ReplyCandidate objects ready for the caller's
    terminal action (draft-save, queue for approval, or direct send).

    Does NOT write the dedup log — caller writes it only when the terminal
    action succeeds.
    """
    config = workflow.config or {}
    account = config.get("account", "iCloud")
    mailbox = config.get("mailbox", "INBOX")
    sender_filter = (config.get("sender_filter") or "").strip()
    body_contains = (config.get("body_contains") or "").strip()
    signature = config.get("signature") or ""
    tone = config.get("tone") or "warm and professional"
    fetch_limit = int(config.get("fetch_limit") or 50)

    # Step 1: list recent messages
    messages = await mcp_client.mail_list_messages(account, mailbox, limit=fetch_limit)
    if not messages:
        log.info("auto_reply_no_messages", workflow_id=workflow.workflow_id)
        return []

    # Step 2: skip anything we've already acknowledged for this workflow
    ids = [str(m.get("id")) for m in messages if m.get("id") is not None]
    already = await _already_handled_ids(session, workflow.workflow_id, ids)

    candidates: list[ReplyCandidate] = []
    for msg in messages:
        if len(candidates) >= max_candidates:
            break
        msg_id = str(msg.get("id") or "")
        if not msg_id or msg_id in already:
            continue

        # Fetch full message to get body + reply-to
        try:
            full = await mcp_client.mail_get_message(account, mailbox, int(msg_id))
        except Exception as e:
            log.warning("mail_get_message_failed", msg_id=msg_id, error=str(e))
            continue

        body = full.get("body") or full.get("content") or ""
        source_from = full.get("sender") or msg.get("sender") or full.get("from") or ""
        source_subject = full.get("subject") or msg.get("subject") or ""

        if not _matches_filters(msg, body, sender_filter, body_contains):
            continue

        to_address = _pick_reply_to(full, source_from)
        if not to_address:
            log.warning("auto_reply_no_reply_to", msg_id=msg_id)
            continue

        # Step 3: LLM-generate the reply
        try:
            llm = llm_service.generate_email_reply(
                source_from=source_from,
                source_subject=source_subject,
                source_body=body,
                signature=signature,
                tone=tone,
            )
        except Exception as e:
            log.error("auto_reply_llm_failed", msg_id=msg_id, error=str(e))
            continue

        result = llm.get("result") or {}
        reply_subject = result.get("subject") or f"Re: {source_subject}"
        reply_body = result.get("body") or ""
        if not reply_body.strip():
            log.warning("auto_reply_empty_body", msg_id=msg_id)
            continue

        usage = llm.get("usage") or {}
        total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))

        candidates.append(
            ReplyCandidate(
                source_message_id=msg_id,
                source_account=account,
                source_mailbox=mailbox,
                source_from=source_from,
                source_subject=source_subject,
                source_body=body,
                to_address=to_address,
                reply_subject=reply_subject,
                reply_body=reply_body,
                llm_tokens=total_tokens,
            )
        )

    return candidates

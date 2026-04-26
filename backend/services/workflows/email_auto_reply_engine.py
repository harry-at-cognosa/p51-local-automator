"""Shared engine for email auto-reply workflows.

Two runners (email_auto_reply_draft, email_auto_reply_approve) both call into
this module. It handles:
  - Fetching recent messages via Apple Mail MCP
  - Filtering candidates by sender and body-substring criteria
  - Skipping already-handled messages via email_auto_reply_log
  - Pulling full body + reply-to from each candidate
  - Collapsing multiple matches from the same to_address into one candidate
    (the most recent), with the older siblings tracked for dedup
  - Generating the reply text with Claude (only for the winning message
    per group, never for siblings — saves tokens)

The terminal action (save to Drafts, or insert into pending_email_replies,
or send directly) is the caller's responsibility. Callers MUST also write
dedup-log rows for both the chosen source_message_id AND every entry in
additional_handled_message_ids so the whole group is marked handled.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import EmailAutoReplyLog, UserWorkflows
from backend.services import llm_service, mcp_client
from backend.services.logger_service import get_logger

log = get_logger("email_auto_reply")


@dataclass
class ReplyCandidate:
    """A matched inbound email with its generated reply draft.

    `additional_handled_message_ids` are sibling messages from the same
    `to_address` group that were superseded by this candidate (the most
    recent one wins). Runners must log dedup rows for them so they don't
    reappear in future runs.
    """
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
    additional_handled_message_ids: list[str] = field(default_factory=list)


@dataclass
class CandidateBatch:
    """Result of one engine pass: candidates + funnel diagnostics.

    Funnel counts let the runner build a step summary that explains where
    matches fell off, so a "0 candidates" outcome is diagnostic instead of
    opaque ("Generated 0 reply draft(s)" tells you nothing about *why*).
    """
    candidates: list[ReplyCandidate] = field(default_factory=list)
    total_listed: int = 0           # messages returned by mail_list_messages
    already_handled: int = 0        # in dedup log for this workflow
    matched_sender: int = 0         # of the un-handled messages, passed sender filter
    matched_both: int = 0           # of those, ALSO passed body filter
    grouped_to_address_count: int = 0  # distinct to_address groups produced
    short_circuit_reason: str = ""  # populated when we returned without scanning
                                    # ('empty_filters' or 'no_messages')

    def funnel_summary(self, sender_filter: str, body_contains: str) -> str:
        """Human-readable funnel string for inclusion in a step's output_summary."""
        if self.short_circuit_reason == "empty_filters":
            return (
                "Skipped run: both sender_filter and body_contains are empty. "
                "Set at least one to avoid acknowledging unrelated mail."
            )
        if self.short_circuit_reason == "no_messages":
            return "Inbox returned 0 messages — nothing to scan."

        parts = [f"Scanned {self.total_listed} inbox messages"]
        if self.already_handled:
            new = self.total_listed - self.already_handled
            parts.append(f"{new} new (skipped {self.already_handled} already-handled)")
        if sender_filter:
            parts.append(
                f"{self.matched_sender} matched sender filter "
                f"'{sender_filter}'"
            )
        if body_contains:
            parts.append(
                f"{self.matched_both} matched body filter "
                f"'{body_contains[:40]}{'…' if len(body_contains) > 40 else ''}'"
            )
        parts.append(f"{self.grouped_to_address_count} after grouping by recipient")
        parts.append(f"{len(self.candidates)} candidate(s) drafted")
        return " → ".join(parts)


_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")

# Apple Mail's default date format, e.g. "Wednesday, April 15, 2026 at 4:11:39 PM"
_DATE_FMT = "%A, %B %d, %Y %I:%M:%S %p"


def _extract_email(raw: str) -> str:
    """Pick the email address out of a 'Name <addr>' or 'addr' string."""
    if not raw:
        return ""
    m = _EMAIL_RE.search(raw)
    return m.group(0) if m else raw.strip()


def _parse_mail_date(date_str: str) -> datetime | None:
    """Parse Apple Mail's date format. Returns None if unparseable."""
    if not date_str:
        return None
    try:
        cleaned = date_str.replace(" at ", " ")
        return datetime.strptime(cleaned, _DATE_FMT).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


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


def _extract_email_from_body(body: str, body_email_field: str) -> str:
    """Find an email address on a labeled line in the body (e.g. `Email: foo@bar.com`).

    `body_email_field` is the literal label to search for, case-insensitive,
    typically followed by an email address on the same line. Squarespace forms
    use `Email:` here. Returns the extracted address, or empty string if not
    found.
    """
    if not body_email_field or not body:
        return ""
    pattern = re.compile(
        rf"{re.escape(body_email_field)}\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{{2,}})",
        re.IGNORECASE,
    )
    m = pattern.search(body)
    return m.group(1) if m else ""


async def _resolve_to_address(
    full_msg: dict,
    source_from: str,
    body: str,
    body_email_field: str,
    account: str,
    mailbox: str,
    message_id: str,
) -> str:
    """Decide where the auto-reply should go.

    Priority order — first non-empty result wins:
      1. Body-field extraction (e.g. Squarespace's `Email:` line) — most reliable
         for known form templates because the submitter explicitly types it
      2. AppleScript Reply-To fetch — Mail.app exposes `reply to` even though
         the MCP doesn't surface it in get_message
      3. MCP `reply_to` / `replyTo` keys (future-proofing if the MCP adds them)
      4. The From address — last resort; for transport senders like
         form-submission@squarespace.info this is wrong, but better than nothing
    """
    # 1. Body-field extraction
    if body_email_field:
        addr = _extract_email_from_body(body, body_email_field)
        if addr:
            return addr

    # 2. AppleScript Reply-To
    try:
        rt_raw = await mcp_client.mail_get_reply_to(account, mailbox, int(message_id))
    except Exception as e:
        log.warning("applescript_reply_to_failed", msg_id=message_id, error=str(e))
        rt_raw = None
    if rt_raw:
        addr = _extract_email(rt_raw)
        if addr:
            return addr

    # 3. MCP reply_to keys (future-proofing)
    mcp_rt = full_msg.get("reply_to") or full_msg.get("replyTo") or ""
    if mcp_rt:
        addr = _extract_email(mcp_rt)
        if addr:
            return addr

    # 4. From — last resort
    return _extract_email(source_from)


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
) -> CandidateBatch:
    """Fetch, filter, group-by-to_address, pick latest-per-group, LLM-draft.

    Two-phase to avoid wasted LLM calls when multiple messages from the same
    submitter would otherwise produce duplicate replies in a single run:

      Phase 1 — list inbox, dedup-skip, fetch each candidate body, apply
      sender/body filters, resolve to_address. Group all survivors by
      to_address. NO LLM calls in this phase.

      Phase 2 — for each to_address group, pick the message with the latest
      Date header. Run the LLM only for that one. Attach the older siblings'
      message IDs to the candidate so the runner can log dedup rows for them.

    Returns a CandidateBatch carrying both the candidates AND funnel counts
    so the runner can produce a diagnostic step summary like "Scanned 50 →
    47 new → 0 matched sender filter 'foo' → no candidates" instead of
    the opaque "Generated 0 reply draft(s)".

    Does NOT write the dedup log — caller writes it only when the terminal
    action succeeds. Caller MUST log both source_message_id AND each entry
    in additional_handled_message_ids.
    """
    config = workflow.config or {}
    account = config.get("account", "iCloud")
    mailbox = config.get("mailbox", "INBOX")
    sender_filter = (config.get("sender_filter") or "").strip()
    body_contains = (config.get("body_contains") or "").strip()
    body_email_field = (config.get("body_email_field") or "").strip()
    signature = config.get("signature") or ""
    tone = config.get("tone") or "warm and professional"
    fetch_limit = int(config.get("fetch_limit") or 50)

    batch = CandidateBatch()

    # Empty-filter safety guard — return immediately, do NOT touch the inbox.
    # Without this fast-path, the loop below would still skip each message via
    # _matches_filters, but only after paying for an MCP body fetch per message
    # (10–30s wasted to return zero candidates).
    if not sender_filter and not body_contains:
        batch.short_circuit_reason = "empty_filters"
        log.info(
            "auto_reply_empty_filters_skipped",
            workflow_id=workflow.workflow_id,
        )
        return batch

    # ── Phase 1: fetch, filter, group by to_address ──────────────
    messages = await mcp_client.mail_list_messages(account, mailbox, limit=fetch_limit)
    batch.total_listed = len(messages)
    if not messages:
        batch.short_circuit_reason = "no_messages"
        log.info("auto_reply_no_messages", workflow_id=workflow.workflow_id)
        return batch

    ids = [str(m.get("id")) for m in messages if m.get("id") is not None]
    already = await _already_handled_ids(session, workflow.workflow_id, ids)
    batch.already_handled = len(already)

    # Per-to_address bucket. Each item is a dict carrying everything the
    # phase-2 winner-picker and LLM-call need.
    grouped: dict[str, list[dict]] = {}

    for msg in messages:
        msg_id = str(msg.get("id") or "")
        if not msg_id or msg_id in already:
            continue

        # Cheap pre-filter on sender BEFORE the (slow) body fetch.
        # mail_list_messages already returns sender info, so we can reject
        # non-matching senders without paying for an MCP get_message call.
        # If sender_filter is empty (only body_contains is set), we must
        # fetch the body anyway, so skip the short-circuit in that case.
        if sender_filter:
            preview_sender = (msg.get("sender") or "") + " " + (msg.get("from") or "")
            if sender_filter.lower() not in preview_sender.lower():
                continue
        # Counts as "matched_sender" if we got past this check (or sender_filter
        # was empty so vacuously passed).
        batch.matched_sender += 1

        try:
            full = await mcp_client.mail_get_message(account, mailbox, int(msg_id))
        except Exception as e:
            log.warning("mail_get_message_failed", msg_id=msg_id, error=str(e))
            continue

        body = full.get("body") or full.get("content") or ""
        source_from = full.get("sender") or msg.get("sender") or full.get("from") or ""
        source_subject = full.get("subject") or msg.get("subject") or ""

        # Full filter check (covers body_contains + empty-filter safety guard).
        if not _matches_filters(msg, body, sender_filter, body_contains):
            continue
        batch.matched_both += 1

        to_address = await _resolve_to_address(
            full_msg=full,
            source_from=source_from,
            body=body,
            body_email_field=body_email_field,
            account=account,
            mailbox=mailbox,
            message_id=msg_id,
        )
        if not to_address:
            log.warning("auto_reply_no_reply_to", msg_id=msg_id)
            continue

        parsed_date = _parse_mail_date(full.get("date") or msg.get("date") or "")

        grouped.setdefault(to_address.lower(), []).append({
            "msg_id": msg_id,
            "to_address": to_address,
            "source_from": source_from,
            "source_subject": source_subject,
            "source_body": body,
            "date": parsed_date,
        })

    batch.grouped_to_address_count = len(grouped)
    if not grouped:
        return batch

    # ── Phase 2: pick latest per group, LLM-generate only the winners ──
    candidates: list[ReplyCandidate] = []

    for _to_key, items in grouped.items():
        # Sort by parsed date descending; missing dates land last.
        # `datetime.min` with a tzinfo is a safe minimum that compares correctly.
        sentinel_min = datetime.min.replace(tzinfo=timezone.utc)
        items.sort(key=lambda x: x["date"] or sentinel_min, reverse=True)

        winner = items[0]
        sibling_ids = [it["msg_id"] for it in items[1:]]

        if len(items) > 1:
            log.info(
                "auto_reply_consolidated_group",
                workflow_id=workflow.workflow_id,
                to_address=winner["to_address"],
                winner_msg_id=winner["msg_id"],
                covered_count=len(sibling_ids),
            )

        # LLM call only on the winner. Pass to_address so the model knows
        # who we're actually replying to — names in the body may refer to
        # other parties.
        try:
            llm = llm_service.generate_email_reply(
                source_from=winner["source_from"],
                source_subject=winner["source_subject"],
                source_body=winner["source_body"],
                to_address=winner["to_address"],
                signature=signature,
                tone=tone,
            )
        except Exception as e:
            log.error("auto_reply_llm_failed", msg_id=winner["msg_id"], error=str(e))
            continue

        result = llm.get("result") or {}
        reply_subject = result.get("subject") or f"Re: {winner['source_subject']}"
        reply_body = result.get("body") or ""
        if not reply_body.strip():
            log.warning("auto_reply_empty_body", msg_id=winner["msg_id"])
            continue

        usage = llm.get("usage") or {}
        total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))

        candidates.append(
            ReplyCandidate(
                source_message_id=winner["msg_id"],
                source_account=account,
                source_mailbox=mailbox,
                source_from=winner["source_from"],
                source_subject=winner["source_subject"],
                source_body=winner["source_body"],
                to_address=winner["to_address"],
                reply_subject=reply_subject,
                reply_body=reply_body,
                llm_tokens=total_tokens,
                additional_handled_message_ids=sibling_ids,
            )
        )

        if len(candidates) >= max_candidates:
            break

    batch.candidates = candidates
    return batch

"""Email Reaper Workflow (Type 8).

Moves to Trash every email from a configurable list of sender addresses
whose date is older than a per-sender "safety window". Operates on ONE
account of ONE type per workflow instance.

Steps:
1. Scan — for each sender, find messages older than (now − safety_window_days)
2. Reap — move matches to Trash (or, in preview mode, touch nothing)
3. Report — write a CSV + Markdown artifact listing every matched message

Config (from user_workflows.config):
    service: "apple_mail" | "gmail" | "gmail_imap"
    account: str          - Mail.app account name (apple_mail)
    account_id: int       - GmailAccounts.id          (gmail OAuth)
    email: str            - consumer Gmail address     (gmail_imap)
    senders: list[{from_address: str, safety_window_days: int}]
    preview_only: bool    - default TRUE; a MISSING key is also treated as
                            TRUE so deletion can never be silently armed
    email_results: {...}  - "email me my results" opt-in block

Deletion is move-to-Trash only (recoverable), never a permanent purge.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns
from backend.services import gmail_client
from backend.services import gmail_imap_client
from backend.services import gmail_password_store
from backend.services import mcp_client
from backend.services import workflow_engine as engine
from backend.services.artifact_meta import build_artifact_meta, wrap_csv_bytes, wrap_markdown
from backend.services.logger_service import get_logger
from backend.services.workflows.email_monitor import _account_label, parse_mail_date

log = get_logger("email_reaper")

WINDOW_MIN = 5
WINDOW_MAX = 365
WINDOW_DEFAULT = 14
FALLBACK_MAX_SENDERS = 150
FALLBACK_FETCH_LIMIT_PER_SENDER = 500

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REPORT_CSV_NAME = "email_reaper_report.csv"
REPORT_MD_NAME = "email_reaper_report.md"


def _is_preview(config: dict) -> bool:
    """Preview unless the config EXPLICITLY sets preview_only to a falsey
    value. Missing/None/anything-truthy → preview (delete nothing)."""
    return config.get("preview_only", True) is not False


def _resolve_single_account(config: dict) -> dict:
    """Resolve the one account this workflow targets. Raises ValueError on
    an unusable config (surfaced as a failed run)."""
    service = config.get("service", "apple_mail")
    if service == "apple_mail":
        return {"service": "apple_mail", "account": config.get("account", "iCloud")}
    if service == "gmail":
        account_id = config.get("account_id")
        if not isinstance(account_id, int):
            raise ValueError(
                "Gmail Email Reaper needs an integer account_id "
                "(the GmailAccounts.id of a connected account)."
            )
        return {"service": "gmail", "account_id": account_id}
    if service == "gmail_imap":
        email = config.get("email")
        if not isinstance(email, str) or not email:
            raise ValueError("gmail_imap service needs an email address.")
        return {"service": "gmail_imap", "email": email}
    raise ValueError(f"Unsupported email service: {service!r}")


def _validate_senders(raw, max_senders: int) -> tuple[list[dict], list[str]]:
    """Clean the configured sender list. Returns (cleaned, notes).

    Each cleaned entry is {from_address, safety_window_days}. Invalid
    addresses are dropped; windows are clamped to [WINDOW_MIN, WINDOW_MAX];
    duplicate addresses (case-insensitive) keep the first occurrence; the
    list is capped at max_senders. `notes` describes what was adjusted."""
    cleaned: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()
    skipped = clamped = duped = 0
    if not isinstance(raw, list):
        raw = []
    for entry in raw:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        addr = str(entry.get("from_address", "")).strip()
        if not _EMAIL_RE.match(addr):
            skipped += 1
            continue
        key = addr.lower()
        if key in seen:
            duped += 1
            continue
        try:
            window = int(entry.get("safety_window_days", WINDOW_DEFAULT))
        except (TypeError, ValueError):
            window = WINDOW_DEFAULT
        if window < WINDOW_MIN:
            window = WINDOW_MIN
            clamped += 1
        elif window > WINDOW_MAX:
            window = WINDOW_MAX
            clamped += 1
        seen.add(key)
        cleaned.append({"from_address": addr, "safety_window_days": window})
        if len(cleaned) >= max_senders:
            break
    capped = max(0, (len([e for e in raw if isinstance(e, dict)]) - skipped - duped) - len(cleaned))
    if skipped:
        notes.append(f"{skipped} invalid address(es) skipped")
    if duped:
        notes.append(f"{duped} duplicate(s) removed")
    if clamped:
        notes.append(f"{clamped} window(s) clamped to [{WINDOW_MIN},{WINDOW_MAX}]")
    if capped:
        notes.append(f"{capped} row(s) over the {max_senders} cap ignored")
    return cleaned, notes


async def _scan_sender(
    session: AsyncSession,
    workflow: UserWorkflows,
    account: dict,
    addr: str,
    window: int,
    cutoff: datetime,
    fetch_limit: int,
    run_id: int,
    imap_password: str | None,
) -> list[dict]:
    """Find messages from `addr` older than `cutoff` for one account.
    Returns match dicts; raises on a hard per-sender failure (caller logs
    and continues)."""
    service = account["service"]
    out: list[dict] = []
    now = datetime.now(timezone.utc)

    if service == "gmail":
        before_date = cutoff.strftime("%Y/%m/%d")
        msgs = await gmail_client.gmail_search_senders_before(
            session, account["account_id"], addr, before_date,
            limit=fetch_limit, workflow_id=workflow.workflow_id, run_id=run_id,
        )
        for m in msgs:
            out.append(_match(addr, window, m, mailbox="(all mail)", now=now))
        return out

    if service == "gmail_imap":
        if not imap_password:
            raise RuntimeError(f"No app password stored for {account['email']}.")
        msgs = await gmail_imap_client.imap_search_senders_before(
            account["email"], imap_password, addr, cutoff, limit=fetch_limit,
        )
        for m in msgs:
            out.append(_match(addr, window, m, mailbox=m.get("mailbox", ""), now=now))
        return out

    if service == "apple_mail":
        # Apple Mail MCP search spans the account; post-filter by date and
        # confirm the sender actually matches (search hits subject too).
        msgs = await mcp_client.mail_search_messages(
            addr, account=account["account"], limit=fetch_limit,
        )
        for m in msgs:
            sender = str(m.get("sender", "")).lower()
            if addr.lower() not in sender:
                continue
            d = parse_mail_date(m.get("date"))
            if d is None or d >= cutoff:
                continue
            out.append(_match(addr, window, m, mailbox=m.get("mailbox", "INBOX"), now=now))
        return out

    raise ValueError(f"Unsupported email service: {service!r}")


def _match(addr: str, window: int, m: dict, *, mailbox: str, now: datetime) -> dict:
    """Build a normalized match record from a backend message dict."""
    d = parse_mail_date(m.get("date"))
    age_days = (now - d).days if d else None
    return {
        "from_address": addr,
        "message_id": str(m.get("id", "")),
        "subject": m.get("subject", ""),
        "date": m.get("date", ""),
        "mailbox": mailbox,
        "age_days": age_days,
        "safety_window_days": window,
        "action": "",
    }


async def _reap(
    session: AsyncSession,
    workflow: UserWorkflows,
    account: dict,
    matches: list[dict],
    run_id: int,
    imap_password: str | None,
) -> int:
    """Move matched messages to Trash. Mutates each match's `action`.
    Returns the count successfully trashed."""
    service = account["service"]
    if not matches:
        return 0

    if service == "gmail":
        ids = [m["message_id"] for m in matches if m["message_id"]]
        trashed = await gmail_client.gmail_trash_messages(
            session, account["account_id"], ids,
            workflow_id=workflow.workflow_id, run_id=run_id,
        )
        trashed_set = set(trashed)
        for m in matches:
            m["action"] = "trashed" if m["message_id"] in trashed_set else "trash failed"
        return len(trashed_set)

    if service == "gmail_imap":
        uids = [m["message_id"] for m in matches if m["message_id"]]
        n = await gmail_imap_client.imap_trash_messages(
            account["email"], imap_password or "", uids,
        )
        # IMAP COPY/EXPUNGE doesn't report per-UID success; reflect the count.
        for i, m in enumerate(matches):
            m["action"] = "trashed" if i < n else "trash failed"
        return n

    if service == "apple_mail":
        trashed = 0
        for m in matches:
            try:
                res = await mcp_client.mail_delete_message(
                    account["account"], m["mailbox"], int(m["message_id"]),
                )
            except Exception as e:  # noqa: BLE001 - degrade per message
                log.warning("apple_mail_trash_failed", message_id=m["message_id"], error=str(e)[:200])
                m["action"] = "trash failed"
                continue
            if res.get("ok"):
                m["action"] = "trashed"
                trashed += 1
            else:
                m["action"] = "trash failed"
        return trashed

    raise ValueError(f"Unsupported email service: {service!r}")


def _build_csv(matches: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["from_address", "subject", "date", "mailbox",
                "age_days", "safety_window_days", "action"])
    for m in matches:
        w.writerow([
            m["from_address"], m["subject"], m["date"], m["mailbox"],
            "" if m["age_days"] is None else m["age_days"],
            m["safety_window_days"], m["action"],
        ])
    return buf.getvalue()


def _build_markdown(
    account: dict, matches: list[dict], per_sender: dict, preview: bool, notes: list[str]
) -> str:
    mode = "PREVIEW (nothing deleted)" if preview else "LIVE (matches moved to Trash)"
    lines = [
        "# Email Reaper report",
        "",
        f"Account: {_account_label(account)}",
        f"Mode: {mode}",
        f"Senders scanned: {len(per_sender)}",
        f"Messages matched: {len(matches)}",
        "",
    ]
    if notes:
        lines.append("Config adjustments: " + "; ".join(notes))
        lines.append("")
    lines.append("## Per-sender summary")
    lines.append("")
    lines.append("| Sender | Window (days) | Cutoff | Matched | Trashed |")
    lines.append("|---|---|---|---|---|")
    for addr, s in per_sender.items():
        lines.append(
            f"| {addr} | {s['window']} | {s['cutoff']} | {s['matched']} | {s['trashed']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


async def run_email_reaper(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the Email Reaper pipeline (scan → reap → report)."""
    config = workflow.config or {}
    preview = _is_preview(config)

    max_senders = (
        await engine.resolve_int_setting(
            session, group_id=workflow.group_id,
            name=engine.SETTING_REAPER_MAX_SENDERS,
            user_override=config.get("reaper_max_senders"),
        ) or FALLBACK_MAX_SENDERS
    )
    fetch_limit = (
        await engine.resolve_int_setting(
            session, group_id=workflow.group_id,
            name=engine.SETTING_REAPER_FETCH_LIMIT_PER_SENDER,
            user_override=config.get("reaper_fetch_limit_per_sender"),
        ) or FALLBACK_FETCH_LIMIT_PER_SENDER
    )

    run = await engine.create_run(
        session, workflow.workflow_id, total_steps=3, trigger=trigger, config=config,
    )
    output_dir = await engine.get_run_output_dir(
        session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id,
    )

    try:
        account = _resolve_single_account(config)
        senders, notes = _validate_senders(config.get("senders"), max_senders)
        if not senders:
            await engine.fail_run(
                session, run,
                "Email Reaper has no valid sender addresses configured.",
            )
            return run

        # Gmail LIVE runs require the gmail.modify scope (granted via reconnect).
        imap_password: str | None = None
        if account["service"] == "gmail" and not preview:
            gacct = await gmail_client._load_active_account(session, account["account_id"])
            if not gmail_client._account_has_modify_scope(gacct):
                await engine.fail_run(
                    session, run,
                    f"Gmail account {gacct.email} lacks delete permission. Reconnect it "
                    "on /app/connections to grant the gmail.modify scope, then re-run. "
                    "(Preview runs work without reconnecting.)",
                )
                return run
        if account["service"] == "gmail_imap":
            imap_password = gmail_password_store.get_app_password(workflow, account["email"])

        # ── Step 1: Scan ──────────────────────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Scan senders")
        now = datetime.now(timezone.utc)
        matches: list[dict] = []
        per_sender: dict[str, dict] = {}
        scan_errors: list[str] = []
        for s in senders:
            addr, window = s["from_address"], s["safety_window_days"]
            cutoff = now - timedelta(days=window)
            per_sender[addr] = {
                "window": window, "cutoff": cutoff.strftime("%Y-%m-%d"),
                "matched": 0, "trashed": 0,
            }
            try:
                found = await _scan_sender(
                    session, workflow, account, addr, window, cutoff,
                    fetch_limit, run.run_id, imap_password,
                )
            except Exception as e:  # noqa: BLE001 - degrade per sender
                log.warning("reaper_scan_failed", sender=addr, error=str(e)[:200])
                scan_errors.append(f"{addr}: {str(e)[:120]}")
                continue
            per_sender[addr]["matched"] = len(found)
            matches.extend(found)
        scan_summary = f"Scanned {len(senders)} sender(s); matched {len(matches)} message(s)."
        if scan_errors:
            scan_summary += f" {len(scan_errors)} sender(s) errored."
        await engine.complete_step(session, step1, output_summary=scan_summary)

        # ── Step 2: Reap ──────────────────────────────────────
        step2 = await engine.start_step(
            session, run.run_id, 2, "Preview matches" if preview else "Move matches to Trash",
        )
        if preview:
            for m in matches:
                m["action"] = "would delete"
            trashed_total = 0
            reap_summary = f"Preview only — {len(matches)} message(s) would be moved to Trash."
        else:
            trashed_total = await _reap(
                session, workflow, account, matches, run.run_id, imap_password,
            )
            for m in matches:
                per_sender[m["from_address"]]["trashed"] += 1 if m["action"] == "trashed" else 0
            reap_summary = f"Moved {trashed_total} message(s) to Trash."
        await engine.complete_step(session, step2, output_summary=reap_summary)

        # ── Step 3: Report ────────────────────────────────────
        step3 = await engine.start_step(session, run.run_id, 3, "Write report")
        meta = build_artifact_meta(workflow, run, kind="reaper_report", filename=REPORT_CSV_NAME)
        csv_path = f"{output_dir}/{REPORT_CSV_NAME}"
        with open(csv_path, "w", newline="") as f:
            f.write(wrap_csv_bytes(meta, _build_csv(matches)))
        await engine.record_artifact(
            session, run.run_id, step3.step_id, csv_path, "csv",
            "Email Reaper deletion report (CSV)",
        )

        md_meta = build_artifact_meta(workflow, run, kind="reaper_report", filename=REPORT_MD_NAME)
        md_path = f"{output_dir}/{REPORT_MD_NAME}"
        with open(md_path, "w") as f:
            f.write(wrap_markdown(md_meta, _build_markdown(account, matches, per_sender, preview, notes)))
        await engine.record_artifact(
            session, run.run_id, step3.step_id, md_path, "md",
            "Email Reaper deletion report (Markdown)",
        )
        await engine.complete_step(
            session, step3,
            output_summary=f"Report written ({'preview' if preview else 'live'}).",
        )

        await engine.complete_run(session, run)
    except Exception as e:  # noqa: BLE001 - surface as a failed run
        log.error("reaper_run_failed", workflow_id=workflow.workflow_id, error=str(e)[:300])
        await engine.fail_run(session, run, str(e)[:1000])

    return run

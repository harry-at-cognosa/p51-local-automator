"""Email Topic Monitor Workflow

Steps:
1. Fetch emails (Apple Mail via MCP, or Gmail via OAuth-connected account)
2. Categorize emails using LLM (topic + urgency)
3. Generate Excel report

Config (from user_workflows.config):
    service: str - "apple_mail" (default) or "gmail" (Track B Phase B1)
    account: str - Mail.app account name (apple_mail only)
    account_id: int - GmailAccounts.id (gmail only)
    mailbox: str - Mailbox / Gmail label (default "INBOX")
    period: str - Time period (default "last 7 days")
    topics: list[str] - Topic names (empty = use defaults)
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import mcp_client
from backend.services import gmail_client
from backend.services import gmail_imap_client
from backend.services import gmail_password_store
from backend.services import llm_service
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import GmailAccounts, UserWorkflows, WorkflowRuns
from sqlalchemy import select

log = get_logger("email_monitor")

DEFAULT_TOPICS = [
    "Business & Finance",
    "Technology & AI",
    "Personal & Social",
    "Marketing & Promotions",
    "Government & Institutional",
]

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "scripts")


def parse_period(period: str) -> datetime:
    """Parse a period string into a cutoff datetime."""
    now = datetime.now(timezone.utc)
    period = period.lower().strip()

    if "24 hour" in period or "1 day" in period:
        return now - timedelta(days=1)
    elif "3 day" in period:
        return now - timedelta(days=3)
    elif "2 week" in period or "14 day" in period:
        return now - timedelta(days=14)
    elif "month" in period or "30 day" in period:
        return now - timedelta(days=30)
    else:
        # Default: 7 days
        days = 7
        for word in period.split():
            try:
                days = int(word)
                break
            except ValueError:
                continue
        return now - timedelta(days=days)


def parse_mail_date(date_str: str) -> datetime | None:
    """Parse a message date string from either backend.

    Handles Apple Mail's localized format ("Wednesday, April 15, 2026 at
    4:11:39 PM") and Gmail's ISO 8601 format with timezone (produced by
    gmail_client._normalize_date).
    """
    if not date_str:
        return None
    # Try ISO 8601 first (Gmail path).
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        pass
    # Apple Mail format.
    try:
        cleaned = date_str.replace(" at ", " ")
        return datetime.strptime(cleaned, "%A, %B %d, %Y %I:%M:%S %p").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        pass
    # Last resort: RFC 2822 (raw Gmail header, before normalization).
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _resolve_accounts(config: dict) -> list[dict]:
    """Return a normalized list of account dicts to fetch from.

    The ad-hoc path stores multiple accounts as `config.accounts = [{service, ...}, ...]`.
    Legacy Type 1 workflows store a single account at the top level
    (`service`, `account` or `account_id`). Translate both into the same
    list-of-dicts shape so the rest of the runner is account-agnostic.
    """
    raw = config.get("accounts")
    if isinstance(raw, list) and raw:
        out: list[dict] = []
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("service"), str):
                out.append(entry)
        if out:
            return out
    service = config.get("service", "apple_mail")
    if service == "apple_mail":
        return [{"service": "apple_mail", "account": config.get("account", "iCloud")}]
    if service == "gmail":
        account_id = config.get("account_id")
        if not isinstance(account_id, int):
            raise ValueError(
                "Gmail-flavored email_monitor needs an integer account_id "
                "(the GmailAccounts.id of a connected account)."
            )
        return [{"service": "gmail", "account_id": account_id}]
    if service == "gmail_imap":
        email = config.get("email")
        if not isinstance(email, str) or not email:
            raise ValueError("gmail_imap service needs an email address.")
        return [{"service": "gmail_imap", "email": email}]
    raise ValueError(f"Unsupported email service: {service!r}")


def _account_label(account: dict) -> str:
    """Stable human-readable label for run summaries / per-message tags."""
    service = account.get("service")
    if service == "apple_mail":
        return f"apple_mail/{account.get('account', 'iCloud')}"
    if service == "gmail":
        # Prefer the looked-up email (enriched by _enrich_gmail_emails at run
        # time) so the run summary reads gmail/h@cognosa.net rather than
        # gmail#1. Falls back to the FK id when the lookup didn't happen
        # (e.g. the account_id no longer points at a row).
        email = account.get("email") or account.get("_resolved_email")
        if email:
            return f"gmail/{email}"
        return f"gmail#{account.get('account_id', '?')}"
    if service == "gmail_imap":
        return f"gmail_imap/{account.get('email', '?')}"
    return service or "unknown"


async def _enrich_gmail_emails(session, accounts: list[dict]) -> None:
    """Look up the email address for each gmail (Workspace OAuth) account
    so per-account run summaries can show the actual email instead of
    the FK id. Mutates the dicts in place; no-op if no gmail rows."""
    ids = [
        a.get("account_id") for a in accounts
        if a.get("service") == "gmail" and isinstance(a.get("account_id"), int)
    ]
    if not ids:
        return
    rows = (await session.execute(
        select(GmailAccounts.id, GmailAccounts.email).where(GmailAccounts.id.in_(ids))
    )).all()
    by_id = {rid: email for rid, email in rows}
    for a in accounts:
        if a.get("service") == "gmail":
            aid = a.get("account_id")
            if isinstance(aid, int) and aid in by_id:
                a["_resolved_email"] = by_id[aid]


async def _fetch_account(
    session: AsyncSession,
    workflow: UserWorkflows,
    account: dict,
    cutoff: datetime,
    mailbox: str,
    run_id: int,
    fetch_limit: int,
) -> list[dict]:
    """Fetch messages for one account. Returns a list — empty on
    per-account failure (caller logs the per-account error and keeps
    going). `fetch_limit` is the resolved email_fetch_limit cap."""
    service = account.get("service")
    if service == "apple_mail":
        return await mcp_client.mail_list_messages(
            account.get("account", "iCloud"), mailbox, limit=fetch_limit,
        )
    if service == "gmail":
        return await gmail_client.gmail_list_messages(
            session, account["account_id"], mailbox=mailbox, limit=fetch_limit,
            workflow_id=workflow.workflow_id, run_id=run_id,
        )
    if service == "gmail_imap":
        email = account["email"]
        password = gmail_password_store.get_app_password(workflow, email)
        if not password:
            raise RuntimeError(
                f"No app password stored for {email} (storage_method="
                f"{(workflow.config or {}).get('storage_method', 'encrypted_db')})"
            )
        return await gmail_imap_client.imap_list_messages(
            email, password, mailbox, cutoff, limit=fetch_limit,
        )
    raise ValueError(f"Unsupported email service: {service!r}")


async def run_email_monitor(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the full email monitoring pipeline.

    Supports multi-account configs via config.accounts (added for the
    Ad-hoc Email Topic Monitor — service value "gmail_imap" via App
    Passwords + IMAP). Legacy single-account configs (service/account
    /account_id at the top level) continue to work via _resolve_accounts.
    """
    config = workflow.config or {}
    mailbox = config.get("mailbox", "INBOX")
    period = config.get("period", "last 7 days")
    topics = config.get("topics") or DEFAULT_TOPICS
    scope = config.get("scope", "")

    accounts = _resolve_accounts(config)
    await _enrich_gmail_emails(session, accounts)

    fetch_limit = (
        await engine.resolve_int_setting(
            session,
            group_id=workflow.group_id,
            name=engine.SETTING_EMAIL_FETCH_LIMIT,
            user_override=config.get("email_fetch_limit"),
        ) or 100
    )

    run = await engine.create_run(session, workflow.workflow_id, total_steps=3, trigger=trigger, config=workflow.config)
    output_dir = await engine.get_run_output_dir(session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

    try:
        # ── Step 1: Fetch emails ──────────────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Fetch emails")

        cutoff = parse_period(period)
        # Per-account fetch with graceful degradation: one failed account
        # logs an error and contributes zero messages, but doesn't abort
        # the run. Other accounts' messages still flow through.
        all_messages: list[dict] = []
        per_account_summaries: list[str] = []
        per_account_errors: list[str] = []
        for account in accounts:
            label = _account_label(account)
            try:
                msgs = await _fetch_account(session, workflow, account, cutoff, mailbox, run.run_id, fetch_limit)
            except Exception as exc:
                log.warning(
                    "email_monitor_account_fetch_failed",
                    run_id=run.run_id, account=label, error=str(exc),
                )
                per_account_errors.append(f"{label}: {exc}")
                continue
            # Tag each message with its originating account so downstream
            # categorization output identifies the source.
            for m in msgs:
                m["source_account"] = label
            all_messages.extend(msgs)
            per_account_summaries.append(f"{label}={len(msgs)}")

        # Filter by date
        filtered = []
        for msg in all_messages:
            msg_date = parse_mail_date(msg.get("date", ""))
            if msg_date and msg_date >= cutoff:
                filtered.append(msg)

        if not filtered:
            summary = (
                f"No emails found in {period} across {len(accounts)} account(s)."
            )
            if per_account_errors:
                summary += f" Errors: {'; '.join(per_account_errors)}"
            await engine.complete_step(session, step1, output_summary=summary)
            await engine.complete_run(session, run)
            return run

        # Fetch content for messages that look actionable (limit API calls)
        enriched = []
        for msg in filtered:
            enriched.append({
                "id": msg.get("id"),
                "sender": msg.get("sender", ""),
                "subject": msg.get("subject", ""),
                "date": msg.get("date", ""),
                "snippet": msg.get("subject", ""),  # Use subject as snippet for now
                "source_account": msg.get("source_account", ""),
            })

        summary = (
            f"Fetched {len(enriched)} emails from {len(accounts)} account(s) "
            f"({', '.join(per_account_summaries)}) — {period}, mailbox {mailbox}"
        )
        if per_account_errors:
            summary += f". Per-account errors: {'; '.join(per_account_errors)}"
        await engine.complete_step(session, step1, output_summary=summary)

        # ── Step 2: Categorize with LLM ──────────────────────
        step2 = await engine.start_step(session, run.run_id, 2, "Categorize emails")

        llm_result = llm_service.categorize_emails(enriched, topics, scope=scope)
        categorized = llm_result["result"]
        usage = llm_result["usage"]
        total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # Merge LLM results back into email data
        cat_map = {}
        if isinstance(categorized, list):
            for item in categorized:
                idx = item.get("index", -1)
                cat_map[idx] = item

        output_emails = []
        for i, email in enumerate(enriched):
            cat = cat_map.get(i, {})
            output_emails.append({
                "topic": cat.get("topic", "Other"),
                "sender": email["sender"],
                "subject": email["subject"],
                "date": email["date"],
                "snippet": email["snippet"],
                "thread_id": str(email.get("id", "")),
                "urgent": cat.get("urgent", False),
                "urgency_reason": cat.get("urgency_reason", ""),
                "source_account": email.get("source_account", ""),
            })

        # Save JSON (wrapped so it self-identifies on disk).
        from backend.services.artifact_meta import build_artifact_meta, wrap_json
        json_meta = build_artifact_meta(
            workflow, run, kind="json", filename="email_categorized.json",
        )
        json_path = os.path.join(output_dir, "email_categorized.json")
        with open(json_path, "w") as f:
            json.dump(wrap_json(json_meta, output_emails), f, indent=2)

        await engine.record_artifact(session, run.run_id, step2.step_id, json_path, "json", "Categorized email data")

        urgent_count = sum(1 for e in output_emails if e.get("urgent"))
        topic_counts = {}
        for e in output_emails:
            t = e.get("topic", "Other")
            topic_counts[t] = topic_counts.get(t, 0) + 1

        summary = f"Categorized {len(output_emails)} emails into {len(topic_counts)} topics. {urgent_count} urgent."
        await engine.complete_step(session, step2, output_summary=summary, llm_tokens=total_tokens)

        # ── Step 3: Generate Excel report ─────────────────────
        step3 = await engine.start_step(session, run.run_id, 3, "Generate Excel report")

        excel_script = os.path.join(SCRIPTS_DIR, "email_to_excel.py")
        if os.path.exists(excel_script):
            result = subprocess.run(
                ["python3", excel_script, json_path, "--output-dir", output_dir],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                await engine.fail_step(session, step3, f"Excel script failed: {result.stderr[:500]}")
                await engine.fail_run(session, run, "Excel generation failed")
                return run

            # Find the generated xlsx
            for fname in os.listdir(output_dir):
                if fname.endswith(".xlsx"):
                    xlsx_path = os.path.join(output_dir, fname)
                    await engine.record_artifact(
                        session, run.run_id, step3.step_id, xlsx_path, "xlsx", "Email monitor Excel report"
                    )
                    break

            await engine.complete_step(session, step3, output_summary=f"Excel report generated: {result.stdout.strip()}")
        else:
            await engine.complete_step(session, step3, output_summary="Excel script not found — skipped")

        await engine.complete_run(session, run)
        log.info("email_monitor_complete", run_id=run.run_id, emails=len(output_emails), urgent=urgent_count)
        return run

    except Exception as e:
        log.error("email_monitor_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

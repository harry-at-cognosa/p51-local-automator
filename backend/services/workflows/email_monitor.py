"""Email Topic Monitor Workflow

Steps:
1. Fetch emails from Apple Mail via MCP
2. Categorize emails using LLM (topic + urgency)
3. Generate Excel report

Config (from user_workflows.config):
    account: str - Mail.app account name (e.g. "iCloud", "harry@cognosa.net")
    mailbox: str - Mailbox name (default "INBOX")
    period: str - Time period (default "last 7 days")
    topics: list[str] - Topic names (empty = use defaults)
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import mcp_client
from backend.services import llm_service
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import UserWorkflows, WorkflowRuns

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
    """Parse Apple Mail date format to datetime."""
    # Format: "Wednesday, April 15, 2026 at 4:11:39 PM"
    try:
        cleaned = date_str.replace(" at ", " ")
        return datetime.strptime(cleaned, "%A, %B %d, %Y %I:%M:%S %p").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


async def run_email_monitor(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the full email monitoring pipeline."""
    config = workflow.config or {}
    account = config.get("account", "iCloud")
    mailbox = config.get("mailbox", "INBOX")
    period = config.get("period", "last 7 days")
    topics = config.get("topics") or DEFAULT_TOPICS
    scope = config.get("scope", "")

    run = await engine.create_run(session, workflow.workflow_id, total_steps=3, trigger=trigger, config=workflow.config)
    output_dir = await engine.get_run_output_dir(session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

    try:
        # ── Step 1: Fetch emails from Apple Mail ──────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Fetch emails")

        cutoff = parse_period(period)
        messages = await mcp_client.mail_list_messages(account, mailbox, limit=100)

        # Filter by date
        filtered = []
        for msg in messages:
            msg_date = parse_mail_date(msg.get("date", ""))
            if msg_date and msg_date >= cutoff:
                filtered.append(msg)

        if not filtered:
            await engine.complete_step(session, step1, output_summary=f"No emails found in {period}")
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
            })

        await engine.complete_step(
            session, step1,
            output_summary=f"Fetched {len(enriched)} emails from {account}/{mailbox} ({period})",
        )

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
            })

        # Save JSON
        json_path = os.path.join(output_dir, "email_categorized.json")
        with open(json_path, "w") as f:
            json.dump(output_emails, f, indent=2)

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

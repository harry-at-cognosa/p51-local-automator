"""Optional final step that emails workflow results to the workflow owner's
designated outbound account.

Entry point: send_results_email(session, workflow, run). Called from
backend/api/workflows.py _run_workflow_background after the per-type runner
returns and the run has reached status='completed'. Always writes a
workflow_run_email_log row (status ∈ sent / failed / skipped_*) so the UI
can decorate run rows with a delivery badge.

Gates (in order, first miss skips):
  1. workflow.type.emailable_results must be TRUE.
  2. workflow.config.email_results.enabled must be TRUE.
  3. workflow.user.outbound_service must be set.
  4. At least one matching artifact must exist for the configured kinds.

Sender dispatch:
  apple_mail → mcp_client.mail_send_email_with_attachments (osascript)
  gmail      → gmail_client.gmail_send_message with attachments
  gmail_imap → gmail_smtp_client.smtp_send via lookup in gmail_password_store

Recipient resolution (always self-send unless apple_mail specifies a
separate destination):
  apple_mail → outbound_identifier JSON {"account_name", "destination"};
               sender = account_name (blank = Mail.app default), recipient
               = destination (required text).
  gmail      → outbound_identifier is the gmail_accounts.id; recipient is
               that account's email_address.
  gmail_imap → outbound_identifier IS the email address; sender + recipient
               are the same.

Body template (v1, fixed):
  Subject: "Results for {workflow_name} ({completed_at})"
  Body: workflow name + run ID + completion time + bullet list of attached
        artifacts. v2 may add per-workflow customization.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import (
    GmailAccounts,
    User,
    UserWorkflows,
    WorkflowArtifacts,
    WorkflowRuns,
    WorkflowRunEmailLog,
    WorkflowTypes,
)
from backend.services.logger_service import get_logger


log = get_logger("results_email")


# Per-type artifact-kind registry. Keys are stable strings the user picks
# from in the workflow config form; values are regex patterns matched
# against artifact basenames at send time.
ARTIFACT_KINDS_BY_TYPE: dict[int, dict[str, str]] = {
    # Type 1 — Email Topic Monitor
    1: {
        "categorized_json": r"^email_categorized\.json$",
        "summary_xlsx": r".*\.xlsx$",
    },
    # Type 2 — Transaction Data Analyzer.
    # analyze_data.py emits multiple xlsx/csv slices, charts, and the
    # step3 summary markdown. Patterns are broad because the slice file
    # names depend on the input. Users can mix and match.
    2: {
        "data_xlsx": r".*\.xlsx$",
        "data_csv": r".*\.csv$",
        "chart_png": r".*\.png$",
        "summary_md": r"^step3_summary_report\.md$",
        "analysis_json": r"^step5_llm_analysis\.json$",
    },
    # Type 3 — Calendar Digest
    3: {
        "digest_json": r"^calendar_digest\.json$",
        "digest_md": r"^calendar_digest\.md$",
    },
    # Type 4 — SQL Query Runner
    4: {
        "results_xlsx": r"_results\.xlsx$",
        "results_csv": r"_results\.csv$",
        "analysis_json": r"_analysis\.json$",
    },
    # Type 7 — Analyze Data Collection (AWF-1).
    # The agentic engine writes files with dynamic names — match by
    # extension. Charts and the draft report are the typical deliverables.
    7: {
        "report_md": r".*\.md$",
        "chart_png": r".*\.png$",
    },
}


# Human-readable labels for the UI checkbox list. Kept here (rather than in
# the frontend) so a single source of truth governs both gating and rendering.
ARTIFACT_KIND_LABELS: dict[str, str] = {
    "categorized_json": "Categorized email JSON",
    "summary_xlsx": "Excel summary report",
    "digest_json": "Calendar digest JSON",
    "digest_md": "Calendar digest Markdown",
    # Type 2 / Type 4 / Type 7 additions
    "data_xlsx": "Filtered data (Excel)",
    "data_csv": "Filtered data (CSV)",
    "chart_png": "Chart images (PNG)",
    "summary_md": "Summary report (Markdown)",
    "analysis_json": "LLM analysis (JSON)",
    "results_xlsx": "Query results (Excel)",
    "results_csv": "Query results (CSV)",
    "report_md": "Analyst report (Markdown)",
}


def kinds_for_type(type_id: int) -> dict[str, str]:
    """Public helper for the workflow-types API to expose the per-type
    artifact kinds (keys + labels) to the frontend without leaking regexes.
    """
    return {
        key: ARTIFACT_KIND_LABELS.get(key, key)
        for key in ARTIFACT_KINDS_BY_TYPE.get(type_id, {})
    }


async def send_results_email(
    session: AsyncSession,
    workflow: UserWorkflows,
    run: WorkflowRuns,
) -> None:
    """Entry point called from _run_workflow_background.

    Best-effort: never raises. All outcomes are recorded in
    workflow_run_email_log; the run's status is not affected by delivery.
    """
    try:
        await _send(session, workflow, run)
    except Exception as exc:  # defensive — orchestrator never propagates
        log.warning(
            "results_email_unhandled",
            run_id=run.run_id,
            workflow_id=workflow.workflow_id,
            error=str(exc)[:300],
        )
        await _record_log(
            session,
            run_id=run.run_id,
            user_id=workflow.user_id,
            service="unknown",
            recipient="",
            subject="",
            status="failed",
            error_message=f"orchestrator-error: {str(exc)[:300]}",
            attachment_count=0,
        )


async def _send(
    session: AsyncSession,
    workflow: UserWorkflows,
    run: WorkflowRuns,
) -> None:
    type_id = workflow.type_id

    # Gate 1: per-type opt-in.
    wf_type = workflow.workflow_type
    if wf_type is None:
        # Eager-load failed somewhere upstream; fetch defensively.
        wf_type = await session.get(WorkflowTypes, type_id)
    if not wf_type or not wf_type.emailable_results:
        return  # silently — types that don't support email-results aren't logged

    # Gate 2: per-workflow opt-in.
    config = workflow.config or {}
    email_cfg = config.get("email_results") or {}
    if not email_cfg.get("enabled"):
        return  # user didn't ask; no log row needed

    # Gate 3: user has an outbound configured.
    user = workflow.user
    if user is None:
        user = await session.get(User, workflow.user_id)
    if not user or not user.outbound_service:
        await _record_log(
            session,
            run_id=run.run_id,
            user_id=workflow.user_id,
            service="",
            recipient="",
            subject=_default_subject(workflow, run),
            status="skipped_no_outbound",
            error_message="User has no outbound email account configured (Profile → Outbound results email).",
            attachment_count=0,
        )
        return

    # Resolve attachments by artifact-kind filter.
    selected_kinds: list[str] = list(email_cfg.get("artifact_kinds") or [])
    patterns = ARTIFACT_KINDS_BY_TYPE.get(type_id, {})
    selected_patterns = [patterns[k] for k in selected_kinds if k in patterns]
    attachments = await _resolve_attachments(session, run, selected_patterns)

    # Gate 4: artifacts must exist if user selected any kinds.
    if selected_kinds and not attachments:
        await _record_log(
            session,
            run_id=run.run_id,
            user_id=workflow.user_id,
            service=user.outbound_service,
            recipient=_recipient_for_log(user),
            subject=_default_subject(workflow, run),
            status="skipped_no_artifacts",
            error_message=f"None of the selected artifact kinds matched any files in the run: {selected_kinds}",
            attachment_count=0,
        )
        return

    subject = _default_subject(workflow, run)
    body = _default_body(workflow, run, attachments)

    try:
        sent_recipient = await _dispatch(session, user, subject, body, attachments)
    except Exception as exc:
        await _record_log(
            session,
            run_id=run.run_id,
            user_id=workflow.user_id,
            service=user.outbound_service or "unknown",
            recipient=_recipient_for_log(user),
            subject=subject,
            status="failed",
            error_message=str(exc)[:500],
            attachment_count=len(attachments),
        )
        return

    await _record_log(
        session,
        run_id=run.run_id,
        user_id=workflow.user_id,
        service=user.outbound_service or "unknown",
        recipient=sent_recipient,
        subject=subject,
        status="sent",
        error_message=None,
        attachment_count=len(attachments),
    )


async def _resolve_attachments(
    session: AsyncSession,
    run: WorkflowRuns,
    patterns: list[str],
) -> list[str]:
    """Return absolute paths of artifacts whose basenames match any of the
    supplied regex patterns. Skips files that don't exist on disk (the
    artifact row may outlive its file under some failure modes).
    """
    if not patterns:
        return []
    compiled = [re.compile(p) for p in patterns]
    result = await session.execute(
        select(WorkflowArtifacts.file_path).where(WorkflowArtifacts.run_id == run.run_id)
    )
    paths = result.scalars().all()
    out: list[str] = []
    for p in paths:
        name = os.path.basename(p)
        if any(c.search(name) for c in compiled):
            if os.path.isfile(p):
                out.append(p)
            else:
                log.warning("results_email_artifact_missing_on_disk", path=p, run_id=run.run_id)
    return out


def _default_subject(workflow: UserWorkflows, run: WorkflowRuns) -> str:
    when = run.completed_at or datetime.now(timezone.utc)
    when_str = when.strftime("%Y-%m-%d %H:%M %Z").strip()
    return f"Results for {workflow.name} ({when_str})"


def _default_body(workflow: UserWorkflows, run: WorkflowRuns, attachments: list[str]) -> str:
    lines = [
        f"Workflow: {workflow.name}",
        f"Run ID: {run.run_id}",
        f"Completed: {run.completed_at.isoformat() if run.completed_at else 'just now'}",
        f"Status: {run.status}",
        "",
    ]
    if attachments:
        lines.append("Attached artifacts:")
        for p in attachments:
            lines.append(f"  • {os.path.basename(p)}")
    else:
        lines.append("(No artifacts attached — workflow produced none of the selected kinds.)")
    lines.append("")
    lines.append("— Local Automator")
    return "\n".join(lines)


def _recipient_for_log(user: User) -> str:
    """Best-effort log-display address. Synchronous; doesn't load Gmail
    accounts row for `gmail` service — that lookup happens at send time."""
    service = user.outbound_service
    ident = user.outbound_identifier or ""
    if service == "apple_mail":
        try:
            blob = json.loads(ident) if ident else {}
            return (blob.get("destination") or "").strip() or "(unset)"
        except json.JSONDecodeError:
            return "(invalid)"
    if service == "gmail_imap":
        return ident
    if service == "gmail":
        return f"gmail_account_id={ident}"
    return ""


async def _dispatch(
    session: AsyncSession,
    user: User,
    subject: str,
    body: str,
    attachments: list[str],
) -> str:
    """Route to the right sender backend. Returns the actual recipient
    address that the message was sent to (used for the log row)."""
    service = user.outbound_service
    ident = user.outbound_identifier or ""

    if service == "apple_mail":
        try:
            blob = json.loads(ident) if ident else {}
        except json.JSONDecodeError:
            raise RuntimeError("Apple Mail outbound_identifier is not valid JSON")
        account_name = (blob.get("account_name") or "").strip() or None
        destination = (blob.get("destination") or "").strip()
        if not destination:
            raise RuntimeError(
                "Apple Mail outbound requires a destination email address (set in Profile)."
            )
        from backend.services.mcp_client import mail_send_email_with_attachments
        await mail_send_email_with_attachments(
            to=destination,
            subject=subject,
            body=body,
            from_account=account_name,
            attachments=attachments,
        )
        return destination

    if service == "gmail":
        try:
            account_id = int(ident)
        except (TypeError, ValueError):
            raise RuntimeError(
                f"Gmail outbound_identifier is not a valid account_id: {ident!r}"
            )
        account = await session.get(GmailAccounts, account_id)
        if not account:
            raise RuntimeError(f"Gmail account id={account_id} not found.")
        if account.status != "active":
            raise RuntimeError(
                f"Gmail account id={account_id} status is {account.status!r} (need 'active'). Reconnect in Profile."
            )
        from backend.services.gmail_client import gmail_send_message
        await gmail_send_message(
            session,
            account_id,
            to=account.email,
            subject=subject,
            body=body,
            attachments=attachments,
        )
        return account.email

    if service == "gmail_imap":
        email_addr = ident
        if not email_addr or "@" not in email_addr:
            raise RuntimeError(
                f"gmail_imap outbound_identifier is not a valid email: {email_addr!r}"
            )
        from backend.services.gmail_password_store import get_app_password_for_email
        from backend.services.gmail_smtp_client import smtp_send
        app_password = await get_app_password_for_email(session, user.group_id, email_addr)
        if not app_password:
            raise RuntimeError(
                f"No App Password stored for {email_addr}. Set it under Profile → Outbound results email."
            )
        await asyncio.to_thread(
            smtp_send,
            from_email=email_addr,
            app_password=app_password,
            to=email_addr,
            subject=subject,
            body=body,
            attachments=attachments,
        )
        return email_addr

    raise RuntimeError(f"Unknown outbound_service: {service!r}")


async def _record_log(
    session: AsyncSession,
    *,
    run_id: int,
    user_id: int,
    service: str,
    recipient: str,
    subject: str,
    status: str,
    error_message: str | None,
    attachment_count: int,
) -> None:
    row = WorkflowRunEmailLog(
        run_id=run_id,
        user_id=user_id,
        service=service or "",
        recipient=recipient or "",
        subject=subject or "",
        status=status,
        error_message=error_message,
        attachment_count=attachment_count,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    log.info(
        "results_email_logged",
        run_id=run_id,
        status=status,
        service=service,
        attachments=attachment_count,
    )

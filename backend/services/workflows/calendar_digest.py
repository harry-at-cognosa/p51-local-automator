"""Calendar Digest Workflow

Steps:
1. Fetch events from the configured calendar service
2. Analyze with LLM (conflicts, importance, prep notes)
3. Generate summary report (JSON + optional Excel)

Config (from user_workflows.config):
    service: str - "apple_calendar" (default) | "google_calendar"
    days: int - Number of days to look ahead (default 7)

  apple_calendar:
    calendars: list[str] - Calendar names (default ["Work", "Family"])

  google_calendar:
    account_id: int - GmailAccounts.id of the connected Google account
    calendar_ids: list[str] - Calendar IDs (from /google-calendar/calendars)
"""
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import google_calendar_client, llm_service, mcp_client
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.db.models import UserWorkflows, WorkflowRuns

log = get_logger("calendar_digest")


def format_date_for_mcp(dt: datetime) -> str:
    """Format datetime for Apple Calendar MCP (e.g. '15 April 2026')."""
    return dt.strftime("%-d %B %Y")


async def _fetch_events_apple(
    config: dict, days: int, now: datetime, end: datetime
) -> tuple[list[dict], list[str], str, str]:
    """Apple Calendar fetch path. Returns (events, calendar_labels,
    from_label, to_label) where the labels are display-friendly."""
    calendars = config.get("calendars", ["Work", "Family"])
    from_date = format_date_for_mcp(now)
    to_date = format_date_for_mcp(end)
    all_events: list[dict] = []
    for cal_name in calendars:
        events = await mcp_client.calendar_list_events(cal_name, from_date, to_date)
        for ev in events:
            ev["calendar"] = cal_name
        all_events.extend(events)
    return all_events, list(calendars), from_date, to_date


async def _fetch_events_google(
    session: AsyncSession,
    workflow: UserWorkflows,
    config: dict,
    days: int,
    now: datetime,
    end: datetime,
) -> tuple[list[dict], list[str], str, str]:
    """Google Calendar fetch path. Returns (events, calendar_labels,
    from_label, to_label). Calendar labels come from the API's display
    summaries so the digest names them the same way the user sees them
    in Google Calendar."""
    account_id = config.get("account_id")
    if not isinstance(account_id, int):
        raise ValueError("config.account_id required when service=google_calendar")
    calendar_ids = config.get("calendar_ids") or []
    if not calendar_ids:
        raise ValueError(
            "config.calendar_ids must list at least one calendar id when service=google_calendar"
        )
    events = await google_calendar_client.calendar_list_events(
        session,
        account_id=account_id,
        calendar_ids=list(calendar_ids),
        time_min=now.replace(tzinfo=timezone.utc),
        time_max=end.replace(tzinfo=timezone.utc),
        workflow_id=workflow.workflow_id,
    )
    # Calendar labels for the report header — derive from the events
    # we got back so empty calendars don't show up if they had no events.
    labels = sorted({ev.get("calendar", "") for ev in events if ev.get("calendar")})
    from_label = now.strftime("%Y-%m-%d")
    to_label = end.strftime("%Y-%m-%d")
    return events, labels, from_label, to_label


async def run_calendar_digest(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    """Execute the calendar digest pipeline."""
    config = workflow.config or {}
    service = (config.get("service") or "apple_calendar").lower()
    days = int(config.get("days", 7))

    run = await engine.create_run(session, workflow.workflow_id, total_steps=2, trigger=trigger, config=workflow.config)
    output_dir = await engine.get_run_output_dir(session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id)

    try:
        # ── Step 1: Fetch events ──────────────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Fetch calendar events")

        now = datetime.now()
        end = now + timedelta(days=days)

        if service == "google_calendar":
            all_events, calendars, from_date, to_date = await _fetch_events_google(
                session, workflow, config, days, now, end
            )
        else:
            all_events, calendars, from_date, to_date = await _fetch_events_apple(
                config, days, now, end
            )

        if not all_events:
            await engine.complete_step(session, step1, output_summary=f"No events found in next {days} days")
            await engine.complete_run(session, run)
            return run

        # Sort chronologically — startDate is ISO 8601 from Google or
        # Apple's locale string; both sort lexically within the same
        # service. (Mixed-service mixing isn't a thing — each run uses
        # one service.)
        all_events.sort(key=lambda e: e.get("startDate", ""))

        await engine.complete_step(
            session, step1,
            output_summary=(
                f"Fetched {len(all_events)} events from {len(calendars)} calendars "
                f"({days} days, {service})"
            ),
        )

        # ── Step 2: Analyze with LLM ─────────────────────────
        step2 = await engine.start_step(session, run.run_id, 2, "Analyze events")

        event_lines = []
        for i, ev in enumerate(all_events):
            loc = ev.get("location") or ""
            if loc:
                loc = loc.replace("\n", ", ")
            event_lines.append(
                f"[{i}] {ev.get('startDate', '')} - {ev.get('endDate', '')} | "
                f"{ev.get('summary', '')} | Calendar: {ev.get('calendar', '')} | Location: {loc}"
            )

        system = """You are a calendar analysis assistant. You will receive a list of calendar events.
For each event, assess:
1. importance: "high", "normal", or "low"
2. conflict: true if it overlaps with another event in the list
3. notes: brief prep notes (e.g. "bring insurance card", "allow travel time", "deadline day")

Also provide an overall summary at the top.

Return JSON with this structure:
{
    "summary": "Overview paragraph of the week ahead",
    "events": [
        {"index": 0, "importance": "high", "conflict": false, "notes": "Medical appointment"},
        ...
    ],
    "conflicts": [
        {"event_a": 0, "event_b": 1, "description": "Both at 8am Thursday"}
    ],
    "urgent_items": ["Event summary that needs attention", ...]
}

Return ONLY the JSON, no other text."""

        user_prompt = f"Analyze these {len(all_events)} calendar events for the next {days} days:\n\n" + "\n".join(event_lines)

        llm_result = llm_service.judge_structured(system, user_prompt)
        analysis = llm_result["result"]
        usage = llm_result["usage"]
        total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # Merge analysis back into events
        event_analysis = {}
        if isinstance(analysis.get("events"), list):
            for item in analysis["events"]:
                event_analysis[item.get("index", -1)] = item

        output_events = []
        for i, ev in enumerate(all_events):
            a = event_analysis.get(i, {})
            loc = ev.get("location") or ""
            if loc:
                loc = loc.replace("\n", ", ")
            output_events.append({
                "date": ev.get("startDate", ""),
                "end_date": ev.get("endDate", ""),
                "summary": ev.get("summary", ""),
                "calendar": ev.get("calendar", ""),
                "location": loc,
                "importance": a.get("importance", "normal"),
                "conflict": a.get("conflict", False),
                "notes": a.get("notes", ""),
            })

        output = {
            "period": f"{from_date} to {to_date}",
            "calendars": calendars,
            "total_events": len(output_events),
            "summary": analysis.get("summary", ""),
            "conflicts": analysis.get("conflicts", []),
            "urgent_items": analysis.get("urgent_items", []),
            "events": output_events,
        }

        json_path = os.path.join(output_dir, "calendar_digest.json")
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)

        await engine.record_artifact(session, run.run_id, step2.step_id, json_path, "json", "Calendar digest data")

        conflict_count = len(analysis.get("conflicts", []))
        urgent_count = len(analysis.get("urgent_items", []))
        summary_text = f"{len(output_events)} events, {conflict_count} conflicts, {urgent_count} urgent items"
        await engine.complete_step(session, step2, output_summary=summary_text, llm_tokens=total_tokens)

        await engine.complete_run(session, run)
        log.info("calendar_digest_complete", run_id=run.run_id, events=len(output_events))
        return run

    except Exception as e:
        log.error("calendar_digest_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run

"""Calendar Digest with Context — workflow type 9.

A spiritual successor to Type 3 (Calendar Digest). Key differences:
  - User-supplied context_text primes the LLM summary
  - Reminder-pattern events excluded from conflict math; rendered as dots
  - Cross-calendar synonym groups collapse duplicates
  - Importance + tentative read from title markers (*Title*, |Title|)
  - Conflicts are visual (PNG grid), not LLM-asserted
  - LLM writes only a single summary paragraph

Type 3 is untouched and keeps running for existing workflows.

Config (workflow.config):
    service: "apple_calendar" | "google_calendar"
    days: 1..7
    context_text: str  — free-form, primes LLM summary
    reminder_patterns: list[str]  — contains-any-of, case-insensitive
    synonym_groups: list[list[str]]  — first matching group wins

  apple_calendar:
    calendars: list[str]
  google_calendar:
    account_id: int
    calendar_ids: list[str]
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns
from backend.services import llm_service
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.workflows._calendar_grid import GridEvent, render_grid
from backend.services.workflows.calendar_digest import (
    _fetch_events_apple,
    _fetch_events_google,
)

log = get_logger("calendar_context_digest")


MAX_DAYS = 7


@dataclass
class CuratedEvent:
    """Post-marker-parse, post-reminder-class, post-synonym-collapse."""
    start_dt: datetime
    end_dt: datetime | None
    title: str            # cleaned (markers stripped)
    calendar: str         # winning calendar after collapse
    location: str
    importance: str       # "important" | "normal"
    tentative: bool
    is_reminder: bool
    also_on: list[str]    # other calendars in the synonym-collapsed group


async def run_calendar_context_digest(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    config = workflow.config or {}
    service = (config.get("service") or "apple_calendar").lower()
    days = _clamp_days(config.get("days", 7))
    context_text: str = (config.get("context_text") or "").strip()
    reminder_patterns: list[str] = [
        p for p in (config.get("reminder_patterns") or []) if isinstance(p, str) and p.strip()
    ]
    synonym_groups: list[list[str]] = _normalize_synonym_groups(config.get("synonym_groups") or [])

    run = await engine.create_run(
        session, workflow.workflow_id, total_steps=2,
        trigger=trigger, config=workflow.config,
    )
    output_dir = await engine.get_run_output_dir(
        session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id,
    )

    try:
        # ── Step 1: Fetch + curate ───────────────────────────
        step1 = await engine.start_step(session, run.run_id, 1, "Fetch + curate events")

        now = datetime.now()
        end = now + timedelta(days=days)
        if service == "google_calendar":
            raw_events, calendars_list, from_label, to_label = await _fetch_events_google(
                session, workflow, config, days, now, end,
            )
        else:
            raw_events, calendars_list, from_label, to_label = await _fetch_events_apple(
                config, days, now, end,
            )

        if not raw_events:
            await engine.complete_step(
                session, step1,
                output_summary=f"No events in next {days} days",
            )
            await engine.complete_run(session, run)
            return run

        curated = _curate_events(raw_events, calendars_list, reminder_patterns, synonym_groups)
        curated.sort(key=lambda e: e.start_dt)

        await engine.complete_step(
            session, step1,
            output_summary=(
                f"Fetched {len(raw_events)} events from {len(calendars_list)} "
                f"calendars; curated to {len(curated)} ({days} days, {service})"
            ),
        )

        # ── Step 2: Render artifacts + LLM summary ──────────
        step2 = await engine.start_step(session, run.run_id, 2, "Render digest + summary")

        # Visual time grid PNG first — deterministic, never blocks on LLM.
        start_date = now.date()
        png_path = os.path.join(output_dir, "calendar_digest.png")
        from backend.services.artifact_meta import (
            build_artifact_meta, wrap_json, wrap_markdown,
        )
        png_meta = build_artifact_meta(
            workflow, run, kind="png", filename="calendar_digest.png",
        )
        attribution = _png_attribution(workflow, run, png_meta)
        grid_events = [_to_grid_event(c) for c in curated]
        render_grid(
            grid_events, start_date, days, png_path,
            attribution_text=attribution,
            calendars_order=calendars_list,
        )
        await engine.record_artifact(
            session, run.run_id, step2.step_id, png_path, "png",
            "Visual 7-day time grid",
        )

        # LLM summary paragraph — narrow scope, primed by context_text.
        summary_text, llm_tokens = _llm_summary(curated, context_text, days, start_date)

        # Markdown
        md_path = os.path.join(output_dir, "calendar_digest.md")
        md_meta = build_artifact_meta(
            workflow, run, kind="md", filename="calendar_digest.md",
        )
        md_body = _render_md(
            period_label=f"{from_label} to {to_label}",
            summary=summary_text,
            curated=curated,
            start_date=start_date,
            days=days,
        )
        with open(md_path, "w") as f:
            f.write(wrap_markdown(md_meta, md_body))
        await engine.record_artifact(
            session, run.run_id, step2.step_id, md_path, "md",
            "Human-readable calendar digest with context",
        )

        # JSON (machine-readable)
        json_path = os.path.join(output_dir, "calendar_digest.json")
        json_meta = build_artifact_meta(
            workflow, run, kind="json", filename="calendar_digest.json",
        )
        json_payload = {
            "period": f"{from_label} to {to_label}",
            "calendars": calendars_list,
            "days": days,
            "context_text": context_text,
            "summary": summary_text,
            "events": [_curated_to_json(c) for c in curated],
        }
        with open(json_path, "w") as f:
            json.dump(wrap_json(json_meta, json_payload), f, indent=2, default=str)
        await engine.record_artifact(
            session, run.run_id, step2.step_id, json_path, "json",
            "Calendar digest data (machine-readable)",
        )

        n_reminders = sum(1 for c in curated if c.is_reminder)
        n_collapsed = sum(1 for c in curated if c.also_on)
        await engine.complete_step(
            session, step2,
            output_summary=(
                f"{len(curated)} curated events "
                f"({n_reminders} reminders, {n_collapsed} synonym-collapsed)"
            ),
            llm_tokens=llm_tokens,
        )

        await engine.complete_run(session, run)
        log.info(
            "calendar_context_digest_complete",
            run_id=run.run_id,
            events=len(curated),
            reminders=n_reminders,
            collapsed=n_collapsed,
        )
        return run

    except Exception as e:
        log.error("calendar_context_digest_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run


# ── Curation helpers ─────────────────────────────────────────


def _clamp_days(raw: Any) -> int:
    try:
        d = int(raw)
    except (TypeError, ValueError):
        d = 7
    if d < 1:
        d = 1
    if d > MAX_DAYS:
        log.warning("calendar_context_digest_days_clamped", requested=d, max=MAX_DAYS)
        d = MAX_DAYS
    return d


def _normalize_synonym_groups(raw: Any) -> list[list[str]]:
    """Coerce groups to list[list[str]], dropping empties."""
    out: list[list[str]] = []
    if not isinstance(raw, list):
        return out
    for group in raw:
        if isinstance(group, list):
            items = [s.strip() for s in group if isinstance(s, str) and s.strip()]
            if items:
                out.append(items)
    return out


def _parse_markers(title: str) -> tuple[str, str, bool]:
    """Parse *Important* and |tentative| markers from the title.

    Strips at most two layers of markers (one of each kind). Returns
    (cleaned_title, importance, tentative).
    """
    s = (title or "").strip()
    importance = "normal"
    tentative = False
    for _ in range(2):
        if len(s) >= 2:
            if s[0] == "*" and s[-1] == "*":
                importance = "important"
                s = s[1:-1].strip()
                continue
            if s[0] == "|" and s[-1] == "|":
                tentative = True
                s = s[1:-1].strip()
                continue
        break
    return s or title.strip(), importance, tentative


def _is_reminder(title_lower: str, patterns: list[str]) -> bool:
    return any(p.lower() in title_lower for p in patterns)


def _find_synonym_group(title_lower: str, groups: list[list[str]]) -> int | None:
    for i, group in enumerate(groups):
        for phrase in group:
            if phrase.lower() in title_lower:
                return i
    return None


def _parse_event_datetime(raw: str) -> datetime | None:
    """Accept ISO 8601 (Google Calendar) OR Apple Calendar MCP's
    natural-language strings like 'Thursday, 4 June 2026 at 8:00:00 am'.

    Returns a naive local datetime (drops tz) for consistent grid placement.
    Returns None if the string can't be parsed by any known format.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # 1) ISO 8601 (Google + anything well-formed)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        pass

    # 2) Apple Calendar MCP locale-formatted strings. Normalize am/pm to
    #    AM/PM since strptime's %p is locale-dependent.
    normalized = s.replace(" am", " AM").replace(" pm", " PM")
    formats = [
        "%A, %d %B %Y at %I:%M:%S %p",   # Thursday, 4 June 2026 at 8:00:00 AM
        "%A, %B %d, %Y at %I:%M:%S %p",  # Thursday, June 4, 2026 at 8:00:00 AM
        "%A, %d %B %Y at %I:%M %p",      # without seconds
        "%A, %B %d, %Y at %I:%M %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    log.warning("calendar_context_digest_unparseable_date", raw=s[:120])
    return None


def _curate_events(
    raw_events: list[dict],
    calendars_order: list[str],
    reminder_patterns: list[str],
    synonym_groups: list[list[str]],
) -> list[CuratedEvent]:
    """Parse markers, classify reminders, collapse synonym + exact-title matches.

    Collapse semantics (applied first to synonym matches, then to exact-title
    matches across calendars on the same day):
      - Winner = the calendar earliest in `calendars_order`. Calendars not
        in the order list sort after listed ones, by name.
      - Reminder propagates from any member.
      - Importance + tentative = OR across the group.
      - Time span = (earliest start, latest end).
      - also_on accumulates non-winner calendars + each member's existing
        also_on list, deduped.

    Exact-title matching uses case-insensitive equality after marker
    stripping and whitespace trimming. Two events titled "Doctor's
    appointment" on the same day in different calendars collapse without
    needing an explicit synonym_groups entry.
    """
    cal_rank = {c: i for i, c in enumerate(calendars_order)}

    def _cal_key(name: str) -> tuple[int, str]:
        return (cal_rank.get(name, len(calendars_order)), name)

    parsed: list[CuratedEvent] = []
    for ev in raw_events:
        start = _parse_event_datetime(ev.get("startDate") or ev.get("date") or "")
        if start is None:
            continue
        end = _parse_event_datetime(ev.get("endDate") or "")
        raw_title = (ev.get("summary") or "").strip()
        title, importance, tentative = _parse_markers(raw_title)
        title_lower = title.lower()
        is_reminder = _is_reminder(title_lower, reminder_patterns)
        parsed.append(CuratedEvent(
            start_dt=start,
            end_dt=end,
            title=title,
            calendar=(ev.get("calendar") or "").strip(),
            location=((ev.get("location") or "").strip()).replace("\n", ", "),
            importance=importance,
            tentative=tentative,
            is_reminder=is_reminder,
            also_on=[],
        ))

    # Pass 1: synonym-group collapse (skipped if no groups configured).
    after_synonym = _collapse_pass(
        parsed,
        bucket_key=lambda e: _synonym_bucket_key(e, synonym_groups),
        cal_key=_cal_key,
    )

    # Pass 2: exact-title collapse on the synonym-pass output. Always on —
    # catches the common case of an identical event mirrored across two
    # calendars where a user just wants one entry.
    after_exact = _collapse_pass(
        after_synonym,
        bucket_key=lambda e: (e.start_dt.date(), "title:" + e.title.strip().lower()),
        cal_key=_cal_key,
    )

    return after_exact


def _synonym_bucket_key(ev: CuratedEvent, groups: list[list[str]]) -> tuple | None:
    """Bucket key for the synonym pass; None means "no synonym match — pass through"."""
    if not groups:
        return None
    gi = _find_synonym_group(ev.title.lower(), groups)
    if gi is None:
        return None
    return (ev.start_dt.date(), "syn:" + str(gi))


def _collapse_pass(
    events: list[CuratedEvent],
    bucket_key,
    cal_key,
) -> list[CuratedEvent]:
    """Generic single-pass collapse.

    `bucket_key(event)` returns a hashable key or None. Events that key to
    None pass through unchanged. Buckets with one member pass through
    unchanged. Buckets with multiple members merge into one CuratedEvent
    via the collapse semantics documented on `_curate_events`.
    """
    buckets: dict = {}
    passthrough: list[CuratedEvent] = []
    for ev in events:
        key = bucket_key(ev)
        if key is None:
            passthrough.append(ev)
            continue
        buckets.setdefault(key, []).append(ev)

    out: list[CuratedEvent] = []
    for members in buckets.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        out.append(_merge_members(members, cal_key))
    return passthrough + out


def _merge_members(members: list[CuratedEvent], cal_key) -> CuratedEvent:
    """Merge a bucket of >=2 events into a single CuratedEvent."""
    members_sorted = sorted(members, key=lambda e: cal_key(e.calendar))
    winner = members_sorted[0]
    others = members_sorted[1:]

    # Accumulate also_on: winner's existing also_on + each other's calendar
    # + each other's existing also_on, deduped and excluding the winner's
    # own calendar.
    also_on: list[str] = list(winner.also_on)
    for m in others:
        for cand in (m.calendar, *m.also_on):
            if cand and cand != winner.calendar and cand not in also_on:
                also_on.append(cand)

    is_reminder = any(m.is_reminder for m in members_sorted)
    importance = "important" if any(m.importance == "important" for m in members_sorted) else "normal"
    tentative = any(m.tentative for m in members_sorted)
    starts = [m.start_dt for m in members_sorted]
    ends = [m.end_dt for m in members_sorted if m.end_dt is not None]
    return CuratedEvent(
        start_dt=min(starts),
        end_dt=max(ends) if ends else None,
        title=winner.title,
        calendar=winner.calendar,
        location=winner.location,
        importance=importance,
        tentative=tentative,
        is_reminder=is_reminder,
        also_on=also_on,
    )


def _to_grid_event(c: CuratedEvent) -> GridEvent:
    return GridEvent(
        start_dt=c.start_dt,
        end_dt=c.end_dt,
        title=c.title,
        calendar=c.calendar,
        importance=c.importance,
        tentative=c.tentative,
        is_reminder=c.is_reminder,
        also_on=tuple(c.also_on),
    )


def _curated_to_json(c: CuratedEvent) -> dict:
    return {
        "start": c.start_dt.isoformat(),
        "end": c.end_dt.isoformat() if c.end_dt else None,
        "title": c.title,
        "calendar": c.calendar,
        "location": c.location,
        "importance": c.importance,
        "tentative": c.tentative,
        "is_reminder": c.is_reminder,
        "also_on": c.also_on,
    }


# ── LLM summary ──────────────────────────────────────────────


def _llm_summary(
    curated: list[CuratedEvent],
    context_text: str,
    days: int,
    start_date,
) -> tuple[str, int]:
    """Single short paragraph. No tags, no conflict list, no per-event notes."""
    if not curated:
        return ("No events scheduled in this window.", 0)

    if context_text:
        context_block = (
            "Here is the job of this digest, provided by the user. Use it as "
            "context for your tone, what to emphasize, and what to ignore:\n"
            f"\n{context_text.strip()}\n"
        )
    else:
        context_block = (
            "No specific context was given for this digest. Write a neutral, "
            "factual one-paragraph overview of the week ahead."
        )

    system = (
        "You write a single brief paragraph (2-5 sentences) summarizing a "
        "user's upcoming calendar.\n\n"
        + context_block +
        "\nHard rules:\n"
        "- One paragraph only. No bullets. No headings. No conflict lists.\n"
        "- Do not invent prep notes, attendees, or details not given.\n"
        "- Do not call out 'conflicts' or 'overlaps' — those are shown in a "
        "separate visual the user already sees.\n"
        "- Events marked 'reminder' are point-in-time signals (e.g. injection "
        "reminders, refills) — describe the week without dwelling on them.\n"
        "- Importance markers in the data ('important' / 'tentative') reflect "
        "the user's own labels; respect them in tone.\n"
        "- Keep it under 600 characters.\n"
        "Return only the paragraph text, no preface."
    )

    event_lines = []
    for c in curated:
        tag_bits = []
        if c.importance == "important":
            tag_bits.append("important")
        if c.tentative:
            tag_bits.append("tentative")
        if c.is_reminder:
            tag_bits.append("reminder")
        if c.also_on:
            tag_bits.append(f"also-on: {', '.join(c.also_on)}")
        tags = f"  [{'; '.join(tag_bits)}]" if tag_bits else ""
        end_str = c.end_dt.isoformat() if c.end_dt else "(no end)"
        event_lines.append(
            f"- {c.start_dt.isoformat()} → {end_str}  {c.title}  ({c.calendar}){tags}"
        )

    user_prompt = (
        f"Window: next {days} days starting {start_date.isoformat()}.\n"
        f"Events ({len(curated)}):\n" + "\n".join(event_lines)
    )

    try:
        result = llm_service.complete_text(system, user_prompt, max_tokens=512)
    except Exception as exc:
        log.warning("calendar_context_digest_llm_error", error=str(exc)[:300])
        return ("(Summary unavailable — LLM call failed.)", 0)

    text = (result.get("text") or "").strip()
    usage = result.get("usage", {})
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return (text or "(Summary empty.)", tokens)


# ── Markdown rendering ──────────────────────────────────────


def _render_md(
    period_label: str,
    summary: str,
    curated: list[CuratedEvent],
    start_date,
    days: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# Calendar Digest with Context — {period_label}")
    lines.append("")
    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")
    lines.append("![Calendar grid](calendar_digest.png)")
    lines.append("")

    # Group by day.
    by_day: dict[Any, list[CuratedEvent]] = {}
    for c in curated:
        by_day.setdefault(c.start_dt.date(), []).append(c)

    for i in range(days):
        d = start_date + timedelta(days=i)
        events = by_day.get(d, [])
        weekday = d.strftime("%A")
        lines.append(f"## {weekday} {d.isoformat()}")
        if not events:
            lines.append("_(no events)_")
            lines.append("")
            continue
        by_cal: dict[str, list[CuratedEvent]] = {}
        for ev in events:
            by_cal.setdefault(ev.calendar or "(unspecified)", []).append(ev)
        for cal in sorted(by_cal):
            lines.append(f"### {cal}")
            for ev in sorted(by_cal[cal], key=lambda e: e.start_dt):
                lines.append(_render_event_line(ev))
            lines.append("")

    return "\n".join(lines)


def _render_event_line(ev: CuratedEvent) -> str:
    time_str = ev.start_dt.strftime("%H:%M")
    if ev.end_dt:
        time_str += "–" + ev.end_dt.strftime("%H:%M")
    title = ev.title
    tags: list[str] = []
    if ev.importance == "important":
        tags.append("important")
    if ev.tentative:
        tags.append("tentative")
    if ev.is_reminder:
        tags.append("reminder")
    if ev.also_on:
        tags.append(f"also on {', '.join(ev.also_on)}")
    tag_str = f"  [{'; '.join(tags)}]" if tags else ""
    loc_str = f"  ({ev.location})" if ev.location else ""
    return f"- {time_str}  {title}{loc_str}{tag_str}"


# ── Misc ─────────────────────────────────────────────────────


def _png_attribution(workflow: UserWorkflows, run: WorkflowRuns, meta: dict) -> str:
    """Small footer baked into the PNG so the image is self-describing
    even when downloaded standalone."""
    return (
        f"workflow #{workflow.workflow_id} ({workflow.name})  "
        f"run #{run.run_id}  generated {meta.get('Generated at', '')}"
    )

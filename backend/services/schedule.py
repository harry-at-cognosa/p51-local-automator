"""Schedule shape, validation, and evaluation for scheduled workflows.

Schedules live in the JSON `UserWorkflows.schedule` column. Two shapes
are supported, discriminated by `kind`:

  ONE-TIME:
    {
      "kind": "one_time",
      "at_local": "2026-05-15T08:00",      # ISO local datetime (no offset)
      "tz": "America/Los_Angeles"          # IANA timezone name
    }

  RECURRING:
    {
      "kind": "recurring",
      "starts_on": "2026-05-15",           # YYYY-MM-DD, inclusive
      "ends_on":   "2027-05-15",           # YYYY-MM-DD, inclusive, ≤ 1yr after starts_on
      "hour": 8,                           # 0–23, local time
      "minute": 0,                         # 0–59, local time
      "tz": "America/Los_Angeles",         # IANA timezone name
      "days_of_week": [0, 1, 2, 3, 4],     # 0=Mon..6=Sun (ISO), non-empty subset
      "week_interval": 1                   # 1=weekly, 2/3/4 supported
    }

Legacy shape — pre-this-design rows have just {"hour", "minute"} with no
`kind` — is silently re-interpreted as a UTC daily recurring schedule.
This keeps existing schedules firing without a migration.
"""
from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal


_UTC = zoneinfo.ZoneInfo("UTC")
_MAX_YEARS = 1
_VALID_WEEK_INTERVALS = {1, 2, 3, 4}


class ScheduleError(ValueError):
    """Raised on malformed schedule input."""


@dataclass
class Schedule:
    """A parsed schedule. Fields not relevant to the kind are None."""
    kind: Literal["one_time", "recurring"]
    tz: zoneinfo.ZoneInfo

    # one_time
    at_local: datetime | None = None  # tz-aware in self.tz

    # recurring
    starts_on: date | None = None
    ends_on: date | None = None
    hour: int | None = None
    minute: int | None = None
    days_of_week: list[int] | None = None
    week_interval: int | None = None


def parse_schedule(d: dict | None) -> Schedule | None:
    """Parse a raw dict into a Schedule. Returns None for no schedule.

    Raises ScheduleError on malformed input — callers can either log
    and skip (polling loop) or surface as a 400 (validator on save).
    """
    if not d:
        return None
    if not isinstance(d, dict):
        raise ScheduleError(f"schedule must be an object, got {type(d).__name__}")

    if "kind" not in d:
        # Legacy {hour, minute} shape — re-interpret as UTC daily recurring.
        try:
            hour = int(d["hour"])
            minute = int(d.get("minute", 0))
        except (KeyError, TypeError, ValueError) as e:
            raise ScheduleError(f"legacy schedule missing/invalid hour: {e}")
        _validate_hour_minute(hour, minute)
        return Schedule(
            kind="recurring",
            tz=_UTC,
            starts_on=date(1970, 1, 1),
            ends_on=date(9999, 12, 31),
            hour=hour,
            minute=minute,
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            week_interval=1,
        )

    tz = _parse_tz(d.get("tz", "UTC"))
    kind = d["kind"]

    if kind == "one_time":
        if "at_local" not in d:
            raise ScheduleError("one_time schedule requires 'at_local'")
        at_local = _parse_local_datetime(d["at_local"], tz)
        return Schedule(kind="one_time", tz=tz, at_local=at_local)

    if kind == "recurring":
        required = ("starts_on", "ends_on", "hour")
        for k in required:
            if k not in d:
                raise ScheduleError(f"recurring schedule requires '{k}'")
        starts_on = _parse_date(d["starts_on"])
        ends_on = _parse_date(d["ends_on"])
        if ends_on < starts_on:
            raise ScheduleError("ends_on must be on or after starts_on")
        if ends_on > starts_on + timedelta(days=365 * _MAX_YEARS):
            raise ScheduleError(f"ends_on must be within {_MAX_YEARS} year(s) of starts_on")

        try:
            hour = int(d["hour"])
            minute = int(d.get("minute", 0))
        except (TypeError, ValueError) as e:
            raise ScheduleError(f"invalid hour/minute: {e}")
        _validate_hour_minute(hour, minute)

        dows_raw = d.get("days_of_week", [0, 1, 2, 3, 4, 5, 6])
        if not isinstance(dows_raw, list) or not dows_raw:
            raise ScheduleError("days_of_week must be a non-empty list of integers 0..6")
        try:
            days_of_week = sorted({int(x) for x in dows_raw})
        except (TypeError, ValueError) as e:
            raise ScheduleError(f"days_of_week entries must be integers: {e}")
        if any(d_ < 0 or d_ > 6 for d_ in days_of_week):
            raise ScheduleError("days_of_week entries must be 0..6 (0=Mon, 6=Sun)")

        try:
            week_interval = int(d.get("week_interval", 1))
        except (TypeError, ValueError) as e:
            raise ScheduleError(f"week_interval must be an integer: {e}")
        if week_interval not in _VALID_WEEK_INTERVALS:
            raise ScheduleError(f"week_interval must be one of {sorted(_VALID_WEEK_INTERVALS)}")

        return Schedule(
            kind="recurring",
            tz=tz,
            starts_on=starts_on,
            ends_on=ends_on,
            hour=hour,
            minute=minute,
            days_of_week=days_of_week,
            week_interval=week_interval,
        )

    raise ScheduleError(f"unknown schedule kind: {kind!r}")


def is_due(s: Schedule, now_utc: datetime, window_seconds: int = 90) -> bool:
    """Return True if the schedule should fire within `window_seconds`
    after its target time relative to `now_utc`.

    The window is forward-only: a fire is "due" iff now ∈ [target, target+window).
    This matches the polling model — we want to fire once per poll, not retroactively.
    """
    now_local = now_utc.astimezone(s.tz)

    if s.kind == "one_time":
        delta = (now_local - s.at_local).total_seconds()
        return 0 <= delta < window_seconds

    today_local = now_local.date()
    if today_local < s.starts_on or today_local > s.ends_on:
        return False
    if today_local.weekday() not in s.days_of_week:
        return False
    weeks_since = (today_local - s.starts_on).days // 7
    if weeks_since % s.week_interval != 0:
        return False

    target = datetime.combine(today_local, time(s.hour, s.minute), tzinfo=s.tz)
    delta = (now_local - target).total_seconds()
    return 0 <= delta < window_seconds


_ONE_TIME_EXPIRY_GRACE_SECONDS = 300


def is_expired(s: Schedule, now_utc: datetime) -> bool:
    """Return True if the schedule is past its end and should auto-disable.

    For one_time: True if `at_local + grace` is in the past — the grace
      window (5 min) keeps a brief backend restart that straddles the
      target time from immediately disabling the job before the fire
      window has had a chance to trigger. The polling-loop ordering
      (is_due before is_expired) handles the in-window case; the grace
      is a belt-and-suspenders for slow polls or longer restarts.
    For recurring: True if today (in local TZ) is past `ends_on`.
    """
    now_local = now_utc.astimezone(s.tz)
    if s.kind == "one_time":
        return (now_local - s.at_local).total_seconds() > _ONE_TIME_EXPIRY_GRACE_SECONDS
    return now_local.date() > s.ends_on


def fired_current_slot(s: Schedule, last_run_at_utc: datetime | None, now_utc: datetime) -> bool:
    """Has the schedule already fired its *current target slot*?

    Compares last_run_at against the schedule's most recent expected fire
    time, not the bare date. This is the correct dedup semantic:

    - Recurring 8 AM, last run at 8:00:30 today → True (don't re-fire).
    - Recurring 8 AM, last run at 2 PM today (manual) → False — the 8 AM
      slot today already passed without us firing it; tomorrow at 8 AM the
      target moves forward and the manual run is before it, so we fire.
    - One-time at 8:05 PM, manual run at 2:08 PM today → False — the 2 PM
      run was not this schedule's target slot; 8:05 PM still fires.
    - One-time at 8:05 PM, last fire at 8:05 PM → True (don't re-fire; the
      one-time path also sets enabled=False as a belt-and-suspenders).

    Comparison is in UTC so DST doesn't introduce off-by-one-hour bugs.
    """
    if last_run_at_utc is None:
        return False

    if s.kind == "one_time":
        target_utc = s.at_local.astimezone(_UTC)
        return last_run_at_utc >= target_utc

    # Recurring: today's target time in the schedule's local TZ, normalized to UTC.
    today_local = now_utc.astimezone(s.tz).date()
    target_local = datetime.combine(today_local, time(s.hour, s.minute), tzinfo=s.tz)
    target_utc = target_local.astimezone(_UTC)
    return last_run_at_utc >= target_utc


def next_fires(s: Schedule, after_utc: datetime, count: int = 5) -> list[datetime]:
    """Return up to `count` upcoming fire times in UTC, strictly after `after_utc`.

    Used by the preview endpoint to show the user when their schedule will
    actually run.
    """
    if s.kind == "one_time":
        at_utc = s.at_local.astimezone(_UTC)
        return [at_utc] if at_utc > after_utc else []

    after_local = after_utc.astimezone(s.tz)
    d = max(s.starts_on, after_local.date())
    fires: list[datetime] = []
    while len(fires) < count and d <= s.ends_on:
        if d.weekday() in s.days_of_week:
            weeks_since = (d - s.starts_on).days // 7
            if weeks_since % s.week_interval == 0:
                fire_local = datetime.combine(d, time(s.hour, s.minute), tzinfo=s.tz)
                if fire_local > after_local:
                    fires.append(fire_local.astimezone(_UTC))
        d += timedelta(days=1)
    return fires


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def human_summary(s: Schedule) -> str:
    """One-line, human-readable summary. Used by the frontend card if it
    chooses not to format client-side, and by tests/logs.
    """
    if s.kind == "one_time":
        return f"One-time: {s.at_local.strftime('%a %b %d %Y at %I:%M %p')} {s.tz.key}"

    days = s.days_of_week or []
    if days == [0, 1, 2, 3, 4]:
        day_part = "Workdays"
    elif days == [0, 1, 2, 3, 4, 5, 6]:
        day_part = "Every day"
    else:
        day_part = ", ".join(_WEEKDAY_NAMES[d] for d in days)

    every = "" if s.week_interval == 1 else f"every {s.week_interval} weeks on "
    time_part = time(s.hour, s.minute).strftime("%I:%M %p").lstrip("0")
    return f"{every}{day_part} at {time_part} {s.tz.key}"


# ── internal helpers ────────────────────────────────────────


def _validate_hour_minute(hour: int, minute: int) -> None:
    if not 0 <= hour <= 23:
        raise ScheduleError(f"hour must be 0..23, got {hour}")
    if not 0 <= minute <= 59:
        raise ScheduleError(f"minute must be 0..59, got {minute}")


def _parse_tz(name: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, TypeError, ValueError) as e:
        raise ScheduleError(f"invalid timezone {name!r}: {e}")


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError) as e:
        raise ScheduleError(f"invalid date {s!r}: {e}")


def _parse_local_datetime(s: str, tz: zoneinfo.ZoneInfo) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError) as e:
        raise ScheduleError(f"invalid datetime {s!r}: {e}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        # Caller may have supplied an offset; normalize to the named TZ.
        dt = dt.astimezone(tz)
    return dt

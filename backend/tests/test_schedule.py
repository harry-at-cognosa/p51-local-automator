"""Unit tests for slot evaluation in backend.services.schedule.

Hermetic — no DB, no HTTP, no filesystem. `now` is always injected, so none
of these depend on the wall clock.

The anchor case is the one that motivated evaluate_slot: on 2026-10-03 and
2026-10-04 the M4 Mac Mini idle-slept straight through workflow 149's 07:10
slot (asleep 06:59:27 to 07:15:48, then 07:01:01 to 07:13:33). The old
forward-only 90-second window meant nothing polled during the slot, so by
the next poll the target had passed and the run was dropped with no log line
and no retry. Two days of digests were lost that way.

Run with: pytest backend/tests/test_schedule.py -v
"""
import zoneinfo
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.schedule import (
    ScheduleError,
    evaluate_slot,
    is_expired,
    latest_slot,
    next_fires,
    parse_schedule,
)

LA = zoneinfo.ZoneInfo("America/Los_Angeles")
_UTC = timezone.utc

WINDOW = 90
CATCHUP = 6 * 3600


def daily(hour, minute=0, tz="America/Los_Angeles", **over):
    """A daily recurring schedule, with room to override any field."""
    d = {
        "kind": "recurring",
        "starts_on": "2026-01-01",
        "ends_on": "2026-12-31",
        "hour": hour,
        "minute": minute,
        "tz": tz,
        "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        "week_interval": 1,
    }
    d.update(over)
    return parse_schedule(d)


def local(y, m, d, hh, mm, tz=LA):
    return datetime(y, m, d, hh, mm, tzinfo=tz).astimezone(_UTC)


# ── the regression this module exists for ───────────────────


def test_slot_missed_during_host_sleep_is_caught_up():
    """Workflow 149's exact shape: 07:10 daily, nothing polls until 07:15:48."""
    s = daily(7, 10)
    woke = local(2026, 10, 3, 7, 15) + timedelta(seconds=48)
    d = evaluate_slot(s, woke, None, WINDOW, CATCHUP, not_before_utc=local(2026, 6, 13, 0, 0))
    assert d.fire is True
    assert d.target_utc == local(2026, 10, 3, 7, 10)
    assert 340 < d.late_seconds < 350  # ~5m48s late
    assert d.missed is False


def test_old_forward_only_window_would_have_dropped_it():
    """Same instant with no catch-up allowance: nothing fires. The old bug."""
    s = daily(7, 10)
    woke = local(2026, 10, 3, 7, 15) + timedelta(seconds=48)
    d = evaluate_slot(s, woke, None, WINDOW, catchup_seconds=0)
    assert d.fire is False
    assert d.missed is True


def test_on_time_fire_inside_the_poll_window():
    s = daily(6, 0)
    d = evaluate_slot(s, local(2026, 10, 3, 6, 0) + timedelta(seconds=24), None, WINDOW, CATCHUP)
    assert d.fire is True
    assert d.late_seconds == 24


def test_slot_lost_beyond_catchup_reports_missed_not_fire():
    """Asleep all day: the run is genuinely lost and must be reported, not fired."""
    s = daily(7, 10)
    d = evaluate_slot(s, local(2026, 10, 3, 20, 0), None, WINDOW, CATCHUP)
    assert d.fire is False
    assert d.missed is True
    assert d.target_utc == local(2026, 10, 3, 7, 10)


# ── dedup: a slot must fire at most once ────────────────────


def test_already_run_slot_does_not_refire():
    s = daily(7, 10)
    target = local(2026, 10, 3, 7, 10)
    d = evaluate_slot(s, target + timedelta(seconds=30), target + timedelta(seconds=4), WINDOW, CATCHUP)
    assert d.fire is False
    assert d.missed is False


def test_catchup_does_not_refire_a_slot_already_caught_up():
    """Second poll after a catch-up fire must be a no-op."""
    s = daily(7, 10)
    target = local(2026, 10, 3, 7, 10)
    first = target + timedelta(minutes=6)
    d1 = evaluate_slot(s, first, None, WINDOW, CATCHUP)
    assert d1.fire is True
    d2 = evaluate_slot(s, first + timedelta(minutes=1), first, WINDOW, CATCHUP)
    assert d2.fire is False


def test_manual_run_after_the_slot_does_not_satisfy_tomorrows_slot():
    """A 2 PM manual run today must not suppress tomorrow's 07:10 fire."""
    s = daily(7, 10)
    manual = local(2026, 10, 3, 14, 0)
    d = evaluate_slot(s, local(2026, 10, 4, 7, 10) + timedelta(seconds=20), manual, WINDOW, CATCHUP)
    assert d.fire is True
    assert d.target_utc == local(2026, 10, 4, 7, 10)


# ── the cross-midnight hole ─────────────────────────────────


def test_late_night_slot_is_caught_up_after_midnight():
    """A 23:50 slot could never be caught up before: past midnight, "today's
    target" is tomorrow's, so the missed slot was invisible."""
    s = daily(23, 50)
    d = evaluate_slot(s, local(2026, 10, 4, 0, 30), None, WINDOW, CATCHUP)
    assert d.fire is True
    assert d.target_utc == local(2026, 10, 3, 23, 50)


# ── guards ──────────────────────────────────────────────────


def test_slot_predating_workflow_creation_is_not_caught_up():
    """Saving an 07:10 daily schedule at 09:00 must not fire 07:10 immediately."""
    s = daily(7, 10)
    created = local(2026, 10, 3, 9, 0)
    d = evaluate_slot(s, created + timedelta(minutes=1), None, WINDOW, CATCHUP, not_before_utc=created)
    assert d.fire is False
    assert d.missed is False


def test_excluded_weekday_never_fires():
    """Workdays-only schedule, evaluated on a Saturday."""
    s = daily(7, 10, days_of_week=[0, 1, 2, 3, 4])
    saturday = local(2026, 10, 3, 7, 10) + timedelta(seconds=20)
    assert saturday.astimezone(LA).weekday() == 5
    d = evaluate_slot(s, saturday, None, WINDOW, catchup_seconds=0)
    assert d.fire is False


def test_catchup_does_not_reach_back_to_an_excluded_day():
    """Sat 07:10 with a workdays-only schedule must not catch up Friday's slot."""
    s = daily(7, 10, days_of_week=[0, 1, 2, 3, 4], starts_on="2026-09-01")
    d = evaluate_slot(s, local(2026, 10, 3, 7, 30), None, WINDOW, CATCHUP)
    assert d.fire is False


def test_week_interval_respected():
    """Fortnightly from a Thursday: the following Thursday is an off week."""
    s = daily(7, 10, starts_on="2026-10-01", week_interval=2)
    on_week = evaluate_slot(s, local(2026, 10, 1, 7, 10) + timedelta(seconds=10), None, WINDOW, CATCHUP)
    assert on_week.fire is True
    off_week = evaluate_slot(s, local(2026, 10, 8, 7, 10) + timedelta(seconds=10), None, WINDOW, CATCHUP)
    assert off_week.fire is False


def test_outside_date_range_never_fires():
    s = daily(7, 10, starts_on="2026-10-10", ends_on="2026-10-20")
    before = evaluate_slot(s, local(2026, 10, 5, 7, 10) + timedelta(seconds=10), None, WINDOW, CATCHUP)
    assert before.fire is False and before.target_utc is None
    after = evaluate_slot(s, local(2026, 10, 25, 7, 10) + timedelta(seconds=10), None, WINDOW, CATCHUP)
    assert after.fire is False


# ── one_time ────────────────────────────────────────────────


def test_one_time_caught_up_after_a_sleep():
    s = parse_schedule({"kind": "one_time", "at_local": "2026-10-03T07:10", "tz": "America/Los_Angeles"})
    d = evaluate_slot(s, local(2026, 10, 3, 7, 25), None, WINDOW, CATCHUP)
    assert d.fire is True


def test_one_time_keeps_its_five_minute_floor_without_catchup():
    """Even with catchup disabled, a one_time keeps the pre-existing grace so
    it cannot land in a dead zone between the fire window and is_expired."""
    s = parse_schedule({"kind": "one_time", "at_local": "2026-10-03T07:10", "tz": "America/Los_Angeles"})
    d = evaluate_slot(s, local(2026, 10, 3, 7, 13), None, WINDOW, catchup_seconds=0)
    assert d.fire is True


def test_one_time_does_not_refire():
    s = parse_schedule({"kind": "one_time", "at_local": "2026-10-03T07:10", "tz": "America/Los_Angeles"})
    target = local(2026, 10, 3, 7, 10)
    d = evaluate_slot(s, target + timedelta(minutes=2), target + timedelta(seconds=3), WINDOW, CATCHUP)
    assert d.fire is False


def test_one_time_in_the_future_has_no_slot_yet():
    s = parse_schedule({"kind": "one_time", "at_local": "2026-10-03T07:10", "tz": "America/Los_Angeles"})
    d = evaluate_slot(s, local(2026, 10, 3, 6, 0), None, WINDOW, CATCHUP)
    assert d.target_utc is None and d.fire is False


# ── DST, where local-time arithmetic goes wrong ─────────────


def test_fires_once_across_spring_forward():
    """2026-03-08 is the US spring-forward. A 07:10 PDT slot still resolves to
    exactly one UTC instant and fires once."""
    s = daily(7, 10, starts_on="2026-03-01")
    d = evaluate_slot(s, local(2026, 3, 8, 7, 10) + timedelta(seconds=20), None, WINDOW, CATCHUP)
    assert d.fire is True
    assert d.target_utc == local(2026, 3, 8, 7, 10)


def test_fires_once_across_fall_back():
    """2026-11-01 is the US fall-back."""
    s = daily(7, 10, starts_on="2026-10-01")
    d = evaluate_slot(s, local(2026, 11, 1, 7, 10) + timedelta(seconds=20), None, WINDOW, CATCHUP)
    assert d.fire is True


# ── helpers kept honest ─────────────────────────────────────


def test_latest_slot_walks_back_past_a_future_target():
    """At 07:00 today's 07:10 target has not arrived, so the most recent slot
    is yesterday's. The day of slack past the horizon is what lets a just-
    outside-the-bound slot be reported missed rather than vanish."""
    s = daily(7, 10)
    at_0700 = local(2026, 10, 10, 7, 0)
    assert latest_slot(s, at_0700, horizon_seconds=60) == local(2026, 10, 9, 7, 10)
    assert latest_slot(s, at_0700, horizon_seconds=0) == local(2026, 10, 9, 7, 10)


def test_next_fires_skips_excluded_days_after_refactor():
    s = daily(7, 10, starts_on="2026-10-01", days_of_week=[0, 1, 2, 3, 4])
    fires = next_fires(s, local(2026, 10, 2, 8, 0), count=3)
    weekdays = [f.astimezone(LA).weekday() for f in fires]
    assert weekdays == [0, 1, 2]  # Mon, Tue, Wed — Sat/Sun skipped


def test_legacy_schedule_shape_still_fires():
    """Pre-design rows carry bare {hour, minute} and mean UTC daily."""
    s = parse_schedule({"hour": 6, "minute": 30})
    now = datetime(2026, 10, 3, 6, 30, 20, tzinfo=_UTC)
    d = evaluate_slot(s, now, None, WINDOW, CATCHUP)
    assert d.fire is True


def test_recurring_expiry_unchanged():
    s = daily(7, 10, ends_on="2026-10-03")
    assert is_expired(s, local(2026, 10, 3, 23, 0)) is False
    assert is_expired(s, local(2026, 10, 4, 0, 30)) is True


def test_malformed_schedule_still_raises():
    with pytest.raises(ScheduleError):
        parse_schedule({"kind": "recurring", "starts_on": "2026-01-01", "ends_on": "2026-12-31", "hour": 99})

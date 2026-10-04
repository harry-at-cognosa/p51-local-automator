"""Scheduler Service — APScheduler-driven fire loop for workflow schedules.

Polls every SCHEDULER_CHECK_INTERVAL_SECONDS. For each workflow with a
schedule and an enabled, active owner:

  1. Parse the schedule JSON via backend.services.schedule.
  2. Ask evaluate_slot what to do about the most recent slot at or before
     now: fire it, report it lost, or leave it alone because it already ran.
  3. Fire via _run_workflow_background with trigger="scheduled"; for
     one_time schedules set enabled=False to prevent re-fire.
  4. If expired (past ends_on for recurring; past at_local for one_time),
     auto-disable.

A slot stays eligible for SCHEDULER_CATCHUP_SECONDS after its target, so a
host that sleeps or a backend that restarts across a slot still runs it on
the next poll instead of dropping the day silently. Past that bound the slot
is logged once at warning level and the run is genuinely lost.

Skip rules: disabled or deleted owner, soft-deleted workflow, missing
or malformed schedule (logged, not raised).
"""
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from backend.config import SCHEDULER_CATCHUP_SECONDS, SCHEDULER_CHECK_INTERVAL_SECONDS
from backend.db.session import SqlAsyncSession
from backend.db.models import User, UserWorkflows
from backend.services.logger_service import get_logger
from backend.services.schedule import (
    Schedule,
    ScheduleError,
    SlotDecision,
    evaluate_slot,
    is_expired,
    parse_schedule,
)

log = get_logger("scheduler")


class WorkflowScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self.is_running = False
        # (workflow_id, slot_utc) pairs already warned about. A lost slot stays
        # lost on every later poll, so without this the warning would repeat
        # once a minute until the next slot. In memory only: a restart re-warns
        # once per slot, which beats needing a table for it.
        self._warned_missed: set[tuple[int, datetime]] = set()

    def start(self):
        if self.is_running:
            return
        self._scheduler.add_job(
            self._check_due_workflows,
            "interval",
            seconds=SCHEDULER_CHECK_INTERVAL_SECONDS,
            id="check_due_workflows",
            replace_existing=True,
        )
        self._scheduler.start()
        self.is_running = True
        log.info("scheduler_started", interval=SCHEDULER_CHECK_INTERVAL_SECONDS)

    def stop(self):
        if not self.is_running:
            return
        self._scheduler.shutdown(wait=False)
        self.is_running = False
        log.info("scheduler_stopped")

    async def _check_due_workflows(self):
        """Find workflows whose schedule should fire now."""
        now_utc = datetime.now(timezone.utc)
        # Pad the window by 30s so a slow poll doesn't drop a fire.
        window_s = SCHEDULER_CHECK_INTERVAL_SECONDS + 30

        async with SqlAsyncSession() as session:
            result = await session.execute(
                select(UserWorkflows)
                .join(User, UserWorkflows.user_id == User.user_id)
                .where(
                    UserWorkflows.enabled == True,  # noqa: E712
                    UserWorkflows.schedule.isnot(None),
                    UserWorkflows.deleted == 0,
                    User.is_active == True,  # noqa: E712
                    User.deleted == 0,
                )
            )
            workflows = result.scalars().all()

        for wf in workflows:
            try:
                schedule = parse_schedule(wf.schedule)
            except ScheduleError as e:
                log.error(
                    "schedule_parse_failed",
                    workflow_id=wf.workflow_id,
                    error=str(e),
                )
                continue
            if schedule is None:
                continue

            # Order matters: the fire decision comes first, so a slot whose
            # target has just passed (poll running late, backend restarted at
            # the wrong moment) still fires before the expiry path kicks in.
            decision = evaluate_slot(
                schedule,
                now_utc,
                wf.last_run_at,
                window_seconds=window_s,
                catchup_seconds=SCHEDULER_CATCHUP_SECONDS,
                not_before_utc=wf.created_at,
            )

            if decision.fire:
                log.info(
                    "scheduler_triggering",
                    workflow_id=wf.workflow_id,
                    name=wf.name,
                    kind=schedule.kind,
                    slot_utc=decision.target_utc.isoformat(),
                    late_seconds=round(decision.late_seconds),
                    catch_up=decision.late_seconds >= window_s,
                )
                self._warned_missed.discard((wf.workflow_id, decision.target_utc))
                asyncio.create_task(self._run_workflow(wf.workflow_id))
                if schedule.kind == "one_time":
                    await self._disable_workflow(wf.workflow_id)
                continue

            if decision.missed:
                self._warn_missed_slot(wf, schedule, decision)

            if is_expired(schedule, now_utc):
                log.info("schedule_expired_auto_disable", workflow_id=wf.workflow_id)
                await self._disable_workflow(wf.workflow_id)

    def _warn_missed_slot(
        self, wf: UserWorkflows, schedule: Schedule, decision: SlotDecision
    ) -> None:
        """Warn once that a scheduled run was lost outright.

        Reached only past the catch-up bound, which means nothing polled for
        hours across the slot. That is worth a line in the log: the run did
        not happen and will not happen.
        """
        key = (wf.workflow_id, decision.target_utc)
        if key in self._warned_missed:
            return
        self._warned_missed.add(key)
        log.warning(
            "scheduler_slot_missed",
            workflow_id=wf.workflow_id,
            name=wf.name,
            kind=schedule.kind,
            slot_utc=decision.target_utc.isoformat(),
            late_seconds=round(decision.late_seconds),
            catchup_seconds=SCHEDULER_CATCHUP_SECONDS,
            hint="nothing polled within the catch-up window — host asleep, backend down, or event loop blocked",
        )
        cutoff = decision.target_utc - timedelta(days=2)
        self._warned_missed = {k for k in self._warned_missed if k[1] >= cutoff}

    async def _disable_workflow(self, workflow_id: int):
        """Flip enabled=False. Used for expired schedules and after a one-time fire."""
        async with SqlAsyncSession() as session:
            wf = await session.get(UserWorkflows, workflow_id)
            if wf is not None:
                wf.enabled = False
                await session.commit()

    async def _run_workflow(self, workflow_id: int):
        """Fire the workflow via the same path as a manual Run Now.

        Same path, different label: the run is recorded with trigger
        "scheduled" so the run history distinguishes a schedule firing from
        somebody pressing Run Now.
        """
        from backend.api.workflows import _run_workflow_background
        await _run_workflow_background(workflow_id, trigger="scheduled")


scheduler = WorkflowScheduler()

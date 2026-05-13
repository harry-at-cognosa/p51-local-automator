"""Scheduler Service — APScheduler-driven fire loop for workflow schedules.

Polls every SCHEDULER_CHECK_INTERVAL_SECONDS. For each workflow with a
schedule and an enabled, active owner:

  1. Parse the schedule JSON via backend.services.schedule.
  2. If expired (past ends_on for recurring; past at_local for one_time),
     auto-disable.
  3. If already fired today (in the schedule's local TZ), skip.
  4. If due (within window), fire via _run_workflow_background and
     for one_time schedules set enabled=False to prevent re-fire.

Skip rules: disabled or deleted owner, soft-deleted workflow, missing
or malformed schedule (logged, not raised).
"""
import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from backend.config import SCHEDULER_CHECK_INTERVAL_SECONDS
from backend.db.session import SqlAsyncSession
from backend.db.models import User, UserWorkflows
from backend.services.logger_service import get_logger
from backend.services.schedule import (
    ScheduleError,
    fired_current_slot,
    is_due,
    is_expired,
    parse_schedule,
)

log = get_logger("scheduler")


class WorkflowScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self.is_running = False

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

            if is_expired(schedule, now_utc):
                log.info("schedule_expired_auto_disable", workflow_id=wf.workflow_id)
                await self._disable_workflow(wf.workflow_id)
                continue

            if fired_current_slot(schedule, wf.last_run_at, now_utc):
                continue

            if is_due(schedule, now_utc, window_seconds=window_s):
                log.info(
                    "scheduler_triggering",
                    workflow_id=wf.workflow_id,
                    name=wf.name,
                    kind=schedule.kind,
                )
                asyncio.create_task(self._run_workflow(wf.workflow_id))
                if schedule.kind == "one_time":
                    await self._disable_workflow(wf.workflow_id)

    async def _disable_workflow(self, workflow_id: int):
        """Flip enabled=False. Used for expired schedules and after a one-time fire."""
        async with SqlAsyncSession() as session:
            wf = await session.get(UserWorkflows, workflow_id)
            if wf is not None:
                wf.enabled = False
                await session.commit()

    async def _run_workflow(self, workflow_id: int):
        """Fire the workflow via the same path as a manual Run Now."""
        from backend.api.workflows import _run_workflow_background
        await _run_workflow_background(workflow_id)


scheduler = WorkflowScheduler()

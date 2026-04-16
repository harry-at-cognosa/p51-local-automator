"""Scheduler Service — APScheduler for per-user workflow schedules.

Checks for workflows with schedules that are due and triggers runs.
Schedule config format in user_workflows.schedule:
{
    "hour": 8,
    "minute": 0,
    "days_of_week": "mon-fri"  // optional, default: every day
}
"""
import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from backend.config import SCHEDULER_CHECK_INTERVAL_SECONDS
from backend.db.session import SqlAsyncSession
from backend.db.models import UserWorkflows
from backend.services.logger_service import get_logger

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
        """Find workflows with schedules that should run now."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        current_minute = now.minute

        async with SqlAsyncSession() as session:
            result = await session.execute(
                select(UserWorkflows).where(
                    UserWorkflows.enabled == True,
                    UserWorkflows.schedule.isnot(None),
                )
            )
            workflows = result.scalars().all()

        for wf in workflows:
            schedule = wf.schedule or {}
            sched_hour = schedule.get("hour")
            sched_minute = schedule.get("minute", 0)

            if sched_hour is None:
                continue

            # Check if it's time to run (within the check interval window)
            if current_hour == sched_hour and abs(current_minute - sched_minute) < (SCHEDULER_CHECK_INTERVAL_SECONDS // 60 + 1):
                # Check if already ran today
                if wf.last_run_at:
                    last_run_date = wf.last_run_at.date() if wf.last_run_at.tzinfo else wf.last_run_at.date()
                    if last_run_date == now.date():
                        continue

                log.info("scheduler_triggering", workflow_id=wf.workflow_id, name=wf.name)
                asyncio.create_task(self._run_workflow(wf.workflow_id))

    async def _run_workflow(self, workflow_id: int):
        """Run a workflow triggered by the scheduler."""
        from backend.api.workflows import _run_workflow_background
        await _run_workflow_background(workflow_id)


# Singleton
scheduler = WorkflowScheduler()

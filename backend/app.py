from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from backend.config import AUTO_START_SCHEDULER, CORS_ORIGINS
from backend.auth.middleware import refresh_last_seen
from backend.services.logger_service import get_logger, setup_logging
from backend.services.scheduler_service import scheduler
from backend.db.seed import run_seed
from backend.db.session import SqlAsyncSession
from backend.db.models import WorkflowRuns


_log = get_logger("startup")

ABANDONED_RUN_AGE_HOURS = 24


async def _reset_abandoned_runs():
    """Flip workflow_runs rows stuck at status='running' for >24h to 'failed'.

    Pairs with the F5 per-workflow run lock: a backend crash or process
    restart mid-run leaves an orphaned 'running' row that would otherwise
    permanently block its workflow (the partial unique index from F5.1
    refuses to start another run while the orphan is active). The watchdog
    runs once per startup and clears any such orphans.

    24h is short enough that a real forgotten orphan unblocks within a day,
    long enough that any plausible workflow's worst-case wall time
    (e.g., AWF-1 at ~30 min) is well under it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ABANDONED_RUN_AGE_HOURS)
    async with SqlAsyncSession() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            update(WorkflowRuns)
            .where(
                WorkflowRuns.status.in_(("pending", "running")),
                WorkflowRuns.started_at < cutoff,
            )
            .values(
                status="failed",
                completed_at=now,
                error_detail=(
                    "Run abandoned (process restart or crash before "
                    "completion); cleared by startup watchdog."
                ),
            )
        )
        await session.commit()
        if result.rowcount:
            _log.info(
                "abandoned_runs_cleared",
                count=result.rowcount,
                cutoff_hours=ABANDONED_RUN_AGE_HOURS,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await _reset_abandoned_runs()
    await run_seed()
    if AUTO_START_SCHEDULER:
        scheduler.start()
        _log.info("scheduler_autostart")
    else:
        _log.info("scheduler_autostart_skipped")
    yield
    if scheduler.is_running:
        scheduler.stop()


app = FastAPI(
    title="Local Automator API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(refresh_last_seen)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

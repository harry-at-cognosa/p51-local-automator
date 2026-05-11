"""Maintenance admin API (Phase M).

Two-tier housekeeping for accumulated run data, superuser-only:

    POST /admin/maintenance/archive  — reversibly hide old runs from
                                       non-superuser views (flips a flag,
                                       leaves data on disk).
    POST /admin/maintenance/purge    — hard-delete old runs (DB rows +
                                       on-disk run subdirs); irreversible.
    GET  /admin/maintenance/log      — history of past sweep actions.

The archive and purge endpoints share their scope/cutoff matching logic
in `_resolve_target_run_ids` so a dry-run preview returns counts that
mirror what a commit would touch.

See docs/phase_M_maintenance_archive_purge_260511.md for the design.
"""
from __future__ import annotations

import os
import shutil
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.db.models import (
    EmailAutoReplyLog,
    MaintenanceLog,
    PendingEmailReplies,
    User,
    UserWorkflows,
    WorkflowArtifacts,
    WorkflowRuns,
    WorkflowSteps,
)
from backend.db.session import async_get_session
from backend.services.workflow_engine import _resolve_file_system_root
from backend.services.logger_service import get_logger

log = get_logger("maintenance_api")


router_maintenance = APIRouter()


# ── Request / response shapes ────────────────────────────────


class ArchiveRequest(BaseModel):
    scope: str = Field(..., description="'all' or 'group'")
    group_id: int | None = Field(
        None, description="Required when scope='group'; ignored otherwise"
    )
    cutoff: date = Field(..., description="YYYY-MM-DD; runs with started_at before this date are eligible")
    dry_run: bool = True


class PurgeRequest(BaseModel):
    scope: str = Field(..., description="'all' or 'group'")
    group_id: int | None = None
    cutoff: date
    dry_run: bool = True
    confirmation: str | None = Field(
        None,
        description="Must equal the literal 'PURGE' when dry_run=false. Rejected with 400 otherwise.",
    )


PURGE_CONFIRMATION_LITERAL = "PURGE"


class MaintenanceResult(BaseModel):
    workflows_affected: int = 0
    runs_affected: int = 0
    steps_affected: int = 0
    artifacts_affected: int = 0
    soft_deleted_workflows_included: int = 0
    # Purge-only fields, left as defaults for archive responses.
    bytes_freed: int | None = None
    workflows_dropped: int = 0


# ── Internal helpers ─────────────────────────────────────────


def _require_superuser(user: User) -> None:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Superuser required"
        )


def _validate_scope(scope: str, group_id: int | None) -> None:
    if scope == "all":
        return
    if scope == "group":
        if group_id is None:
            raise HTTPException(
                status_code=400, detail="group_id required when scope='group'"
            )
        return
    raise HTTPException(status_code=400, detail="scope must be 'all' or 'group'")


def _cutoff_to_datetime(cutoff: date) -> datetime:
    """Treat cutoff as start-of-day UTC. Runs with started_at strictly
    before this instant are eligible."""
    return datetime.combine(cutoff, time.min, tzinfo=timezone.utc)


async def _resolve_target_run_ids(
    session: AsyncSession,
    scope: str,
    group_id: int | None,
    cutoff: date,
    *,
    only_unarchived: bool = True,
) -> list[int]:
    """Return run_ids matching the sweep criteria.

    A run is targeted when:
      - (the parent workflow is soft-deleted, no date filter applied), OR
      - the run's started_at is strictly before the cutoff,

    AND it's still active (archived = false) when `only_unarchived` is set
    (the archive path uses this; purge ignores `archived` since it deletes
    anyway).

    Group filter, when scope='group', constrains to workflows in that group.
    """
    cutoff_dt = _cutoff_to_datetime(cutoff)

    stmt = (
        select(WorkflowRuns.run_id)
        .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
        .where(
            or_(
                UserWorkflows.deleted == 1,
                WorkflowRuns.started_at < cutoff_dt,
            )
        )
    )
    if only_unarchived:
        stmt = stmt.where(WorkflowRuns.archived.is_(False))
    if scope == "group":
        stmt = stmt.where(UserWorkflows.group_id == group_id)

    rows = await session.execute(stmt)
    return [r[0] for r in rows.all()]


async def _count_descendants(
    session: AsyncSession, run_ids: list[int]
) -> tuple[int, int, int, int]:
    """Return (workflow_count, runs_count, steps_count, artifacts_count) for
    the given set of run_ids. workflow_count is DISTINCT(workflow_id).
    """
    if not run_ids:
        return 0, 0, 0, 0

    workflows_count = await session.scalar(
        select(func.count(func.distinct(WorkflowRuns.workflow_id))).where(
            WorkflowRuns.run_id.in_(run_ids)
        )
    ) or 0

    runs_count = len(run_ids)

    steps_count = await session.scalar(
        select(func.count(WorkflowSteps.step_id)).where(
            WorkflowSteps.run_id.in_(run_ids)
        )
    ) or 0

    artifacts_count = await session.scalar(
        select(func.count(WorkflowArtifacts.artifact_id)).where(
            WorkflowArtifacts.run_id.in_(run_ids)
        )
    ) or 0

    return int(workflows_count), int(runs_count), int(steps_count), int(artifacts_count)


async def _count_soft_deleted_workflows_in_set(
    session: AsyncSession, run_ids: list[int]
) -> int:
    """Distinct workflow_id count among the run_ids whose parent workflow
    is soft-deleted. Surfaced in the result so the operator can tell how
    much of the sweep is the auto-included soft-deleted bucket."""
    if not run_ids:
        return 0
    return int(
        await session.scalar(
            select(func.count(func.distinct(WorkflowRuns.workflow_id)))
            .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
            .where(WorkflowRuns.run_id.in_(run_ids))
            .where(UserWorkflows.deleted == 1)
        ) or 0
    )


def _dir_size_bytes(path: str) -> int:
    """Recursive byte total for a directory tree. Returns 0 if the path
    doesn't exist or any walk error happens (we don't fail the sweep over
    a missing dir).
    """
    if not os.path.isdir(path):
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


async def _resolve_run_paths(
    session: AsyncSession, run_ids: list[int]
) -> list[tuple[int, str]]:
    """Resolve absolute on-disk run directories for the given run_ids.

    Returns a list of (run_id, run_dir_abspath). Skips runs whose group
    has no file_system_root configured (they couldn't have been written
    in the first place; nothing to delete).
    """
    if not run_ids:
        return []

    rows = await session.execute(
        select(
            WorkflowRuns.run_id,
            UserWorkflows.group_id,
            UserWorkflows.user_id,
            UserWorkflows.workflow_id,
        )
        .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
        .where(WorkflowRuns.run_id.in_(run_ids))
    )

    # Cache file_system_root per group_id — the resolution chain is
    # group_settings → api_settings, so two runs in the same group share
    # the same root.
    root_cache: dict[int, str | None] = {}
    out: list[tuple[int, str]] = []
    for run_id, group_id, user_id, workflow_id in rows.all():
        if group_id not in root_cache:
            try:
                root_cache[group_id] = await _resolve_file_system_root(session, group_id)
            except RuntimeError:
                root_cache[group_id] = None
        root = root_cache[group_id]
        if not root:
            continue
        out.append(
            (run_id, os.path.join(root, str(group_id), str(user_id), str(workflow_id), str(run_id)))
        )
    return out


async def _write_maintenance_log(
    session: AsyncSession,
    *,
    operation: str,
    user_id: int,
    scope: str,
    group_id: int | None,
    cutoff: date,
    counts: MaintenanceResult,
    bytes_freed: int | None = None,
    error_detail: str | None = None,
) -> None:
    log = MaintenanceLog(
        operation=operation,
        user_id=user_id,
        scope=scope,
        scope_group_id=group_id if scope == "group" else None,
        cutoff=_cutoff_to_datetime(cutoff),
        workflows_affected=counts.workflows_affected,
        runs_affected=counts.runs_affected,
        steps_affected=counts.steps_affected,
        artifacts_affected=counts.artifacts_affected,
        bytes_freed=bytes_freed,
        error_detail=error_detail,
    )
    session.add(log)


# ── Archive endpoint (M.3) ──────────────────────────────────


@router_maintenance.post(
    "/admin/maintenance/archive", response_model=MaintenanceResult
)
async def archive_runs(
    payload: ArchiveRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
) -> MaintenanceResult:
    """Archive runs older than `cutoff` (plus all runs of soft-deleted
    workflows, regardless of date). Dry-run returns counts only; commit
    flips archived=true and writes a maintenance_log row.
    """
    _require_superuser(user)
    _validate_scope(payload.scope, payload.group_id)

    run_ids = await _resolve_target_run_ids(
        session, payload.scope, payload.group_id, payload.cutoff
    )
    workflows_count, runs_count, steps_count, artifacts_count = await _count_descendants(
        session, run_ids
    )
    soft_deleted_workflows = await _count_soft_deleted_workflows_in_set(session, run_ids)

    result = MaintenanceResult(
        workflows_affected=workflows_count,
        runs_affected=runs_count,
        steps_affected=steps_count,
        artifacts_affected=artifacts_count,
        soft_deleted_workflows_included=soft_deleted_workflows,
    )

    if payload.dry_run:
        return result

    if run_ids:
        await session.execute(
            update(WorkflowRuns)
            .where(WorkflowRuns.run_id.in_(run_ids))
            .values(archived=True)
        )
    await _write_maintenance_log(
        session,
        operation="archive",
        user_id=user.user_id,
        scope=payload.scope,
        group_id=payload.group_id,
        cutoff=payload.cutoff,
        counts=result,
    )
    await session.commit()
    return result


# ── Purge endpoint (M.4) ────────────────────────────────────


@router_maintenance.post(
    "/admin/maintenance/purge", response_model=MaintenanceResult
)
async def purge_runs(
    payload: PurgeRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
) -> MaintenanceResult:
    """Hard-delete runs older than `cutoff` (plus all runs of soft-deleted
    workflows). Drops descendant rows (steps, artifacts, pending replies,
    auto-reply log entries) and rm -rf's each run's on-disk subdirectory.
    After the run sweep, any soft-deleted workflow that now has zero runs
    is dropped entirely.

    Commit (dry_run=false) requires `confirmation` == 'PURGE'.
    """
    _require_superuser(user)
    _validate_scope(payload.scope, payload.group_id)

    # Purge ignores the archived flag — already-archived rows are still
    # eligible for hard deletion at or before the cutoff.
    run_ids = await _resolve_target_run_ids(
        session,
        payload.scope,
        payload.group_id,
        payload.cutoff,
        only_unarchived=False,
    )
    workflows_count, runs_count, steps_count, artifacts_count = await _count_descendants(
        session, run_ids
    )
    soft_deleted_workflows = await _count_soft_deleted_workflows_in_set(session, run_ids)

    # For the dry-run preview, sum bytes from on-disk run dirs so the
    # operator sees the space that would be freed before committing.
    run_paths = await _resolve_run_paths(session, run_ids)
    bytes_total = sum(_dir_size_bytes(p) for _r, p in run_paths)

    # How many soft-deleted workflows would have zero remaining runs and
    # therefore be dropped after the purge? Mirrors the actual cleanup
    # query below: deleted=1 AND no surviving runs (where "surviving"
    # means run_ids not in the purge set).
    workflows_dropped_count = int(
        await session.scalar(
            select(func.count(UserWorkflows.workflow_id))
            .where(UserWorkflows.deleted == 1)
            .where(
                ~select(WorkflowRuns.run_id)
                .where(WorkflowRuns.workflow_id == UserWorkflows.workflow_id)
                .where(WorkflowRuns.run_id.notin_(run_ids) if run_ids else True)
                .exists()
            )
        ) or 0
    )

    result = MaintenanceResult(
        workflows_affected=workflows_count,
        runs_affected=runs_count,
        steps_affected=steps_count,
        artifacts_affected=artifacts_count,
        soft_deleted_workflows_included=soft_deleted_workflows,
        bytes_freed=bytes_total,
        workflows_dropped=workflows_dropped_count,
    )

    if payload.dry_run:
        return result

    if payload.confirmation != PURGE_CONFIRMATION_LITERAL:
        raise HTTPException(
            status_code=400,
            detail=f"Purge commit requires confirmation='{PURGE_CONFIRMATION_LITERAL}'",
        )

    # Build a lookup of run_id → on-disk dir so each per-run iteration
    # can rm without re-querying.
    path_by_run = dict(run_paths)

    bytes_freed_actual = 0
    errors: list[str] = []

    for run_id in run_ids:
        try:
            # Descendant rows first to satisfy FKs. Order matters:
            #   workflow_artifacts → workflow_steps → email_auto_reply_log
            #   (which FK-references pending_email_replies) → pending_email_replies
            #   → workflow_runs row itself.
            await session.execute(
                delete(WorkflowArtifacts).where(WorkflowArtifacts.run_id == run_id)
            )
            await session.execute(
                delete(WorkflowSteps).where(WorkflowSteps.run_id == run_id)
            )
            # auto_reply_log rows can reference pending_email_replies by
            # pending_id; null those first so the pending-replies delete
            # doesn't violate the FK. Cheaper than a CASCADE migration.
            await session.execute(
                delete(EmailAutoReplyLog).where(
                    EmailAutoReplyLog.pending_id.in_(
                        select(PendingEmailReplies.pending_id).where(
                            PendingEmailReplies.run_id == run_id
                        )
                    )
                )
            )
            await session.execute(
                delete(PendingEmailReplies).where(PendingEmailReplies.run_id == run_id)
            )
            await session.execute(
                delete(WorkflowRuns).where(WorkflowRuns.run_id == run_id)
            )

            run_dir = path_by_run.get(run_id)
            if run_dir and os.path.isdir(run_dir):
                bytes_freed_actual += _dir_size_bytes(run_dir)
                shutil.rmtree(run_dir, ignore_errors=True)
        except Exception as e:  # pragma: no cover - defensive
            errors.append(f"run_id={run_id}: {str(e)[:200]}")
            log.error("maintenance_purge_run_failed", run_id=run_id, error=str(e)[:500])
            # Continue to next run; don't bail the whole sweep.

    # After the run sweep, drop soft-deleted workflows that now have no
    # remaining runs. This is the same set we projected in the dry-run.
    drop_stmt = (
        delete(UserWorkflows)
        .where(UserWorkflows.deleted == 1)
        .where(
            ~select(WorkflowRuns.run_id)
            .where(WorkflowRuns.workflow_id == UserWorkflows.workflow_id)
            .exists()
        )
    )
    drop_result = await session.execute(drop_stmt)
    workflows_dropped_actual = drop_result.rowcount or 0

    result.bytes_freed = bytes_freed_actual
    result.workflows_dropped = int(workflows_dropped_actual)

    await _write_maintenance_log(
        session,
        operation="purge",
        user_id=user.user_id,
        scope=payload.scope,
        group_id=payload.group_id,
        cutoff=payload.cutoff,
        counts=result,
        bytes_freed=bytes_freed_actual,
        error_detail="; ".join(errors)[:1000] if errors else None,
    )
    await session.commit()
    return result

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.dashboard import _run_scope_filter
from backend.db.session import async_get_session, SqlAsyncSession
from backend.db.models import (
    EmailAutoReplyLog,
    PendingEmailReplies,
    User,
    WorkflowCategories,
    WorkflowTypes,
    UserWorkflows,
    WorkflowRuns,
    WorkflowSteps,
    WorkflowArtifacts,
)
from backend.db.schemas import (
    WorkflowCategoryRead,
    WorkflowCategoryUpdate,
    WorkflowTypeRead,
    WorkflowTypeUpdate,
    UserWorkflowCreate,
    UserWorkflowRead,
    UserWorkflowListRead,
    UserWorkflowUpdate,
    BulkDeleteRequest,
    PendingEmailReplyRead,
    PendingEmailReplyActionRequest,
    WorkflowRunRead,
    WorkflowStepRead,
    WorkflowArtifactRead,
)
from backend.auth.users import current_active_user
from backend.services import gmail_client, mcp_client
from backend.services import secrets as crypto
from backend.services.logger_service import get_logger
from backend.services.workflows.calendar_digest import run_calendar_digest
from backend.services.workflows.analyze_data_collection import run_analyze_data_collection
from backend.services.workflows.data_analyzer import run_data_analyzer
from backend.services.workflows.email_auto_reply_approve import run_email_auto_reply_approve
from backend.services.workflows.email_auto_reply_draft import run_email_auto_reply_draft
from backend.services.workflows.email_monitor import run_email_monitor
from backend.services.workflows.sql_runner import run_sql_runner

log = get_logger("workflows_api")

router_workflows = APIRouter()


def _normalize_secrets_in_config(
    config: dict | None,
    type_id: int,
    existing_config: dict | None = None,
) -> dict | None:
    """Transform plaintext secrets into encrypted form before persisting.

    For type 4 (SQL Query Runner): a non-empty plaintext `connection_string`
    is encrypted via secrets.encrypt_to_b64 and stored under
    `connection_string_enc`. The plaintext key is dropped. An empty
    plaintext during an update preserves any existing
    `connection_string_enc` from the prior config — so editing
    unrelated fields (query, query_name) doesn't wipe the secret.

    For other types: passthrough.
    """
    if type_id != 4 or not config:
        return config
    config = dict(config)
    cs = config.get("connection_string", "")
    if cs:
        config["connection_string_enc"] = crypto.encrypt_to_b64(cs)
    elif existing_config and existing_config.get("connection_string_enc"):
        config["connection_string_enc"] = existing_config["connection_string_enc"]
    config.pop("connection_string", None)
    return config


# ── Workflow Categories (catalog) ─────────────────────────────


@router_workflows.get("/workflow-categories", response_model=list[WorkflowCategoryRead])
async def list_workflow_categories(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    result = await session.execute(
        select(WorkflowCategories)
        .where(WorkflowCategories.enabled == True)
        .order_by(WorkflowCategories.sort_order, WorkflowCategories.category_id)
    )
    return result.scalars().all()


# ── Workflow Types (catalog) ─────────────────────────────────


@router_workflows.get("/workflow-types", response_model=list[WorkflowTypeRead])
async def list_workflow_types(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    # Cluster by category (sort_order, then category_id as a tie-break),
    # then types within that cluster by type_id (natural seed order;
    # workflow_types has no sort_order column today). Feeds the Dashboard
    # card grid and the Create-workflow dropdown the same shape.
    result = await session.execute(
        select(WorkflowTypes)
        .join(WorkflowCategories)
        .options(selectinload(WorkflowTypes.category))
        .where(WorkflowTypes.enabled == True)
        .order_by(
            WorkflowCategories.sort_order,
            WorkflowCategories.category_id,
            WorkflowTypes.type_id,
        )
    )
    return result.scalars().all()


# ── Catalog admin (superuser-only edits to categories/types) ─


def _require_superuser(user: User) -> None:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")


@router_workflows.get("/admin/workflow-categories", response_model=list[WorkflowCategoryRead])
async def admin_list_workflow_categories(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """List ALL categories (including disabled) for the admin CRUD page."""
    _require_superuser(user)
    result = await session.execute(
        select(WorkflowCategories).order_by(WorkflowCategories.sort_order, WorkflowCategories.category_id)
    )
    return result.scalars().all()


@router_workflows.patch("/admin/workflow-categories/{category_id}", response_model=WorkflowCategoryRead)
async def admin_update_workflow_category(
    category_id: int,
    body: WorkflowCategoryUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_superuser(user)
    category = await session.get(WorkflowCategories, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await session.commit()
    await session.refresh(category)
    return category


@router_workflows.get("/admin/workflow-types", response_model=list[WorkflowTypeRead])
async def admin_list_workflow_types(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """List ALL types (including disabled) for the admin CRUD page."""
    _require_superuser(user)
    result = await session.execute(
        select(WorkflowTypes)
        .options(selectinload(WorkflowTypes.category))
        .order_by(WorkflowTypes.type_id)
    )
    return result.scalars().all()


@router_workflows.patch("/admin/workflow-types/{type_id}", response_model=WorkflowTypeRead)
async def admin_update_workflow_type(
    type_id: int,
    body: WorkflowTypeUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    _require_superuser(user)
    wf_type = await session.get(WorkflowTypes, type_id)
    if not wf_type:
        raise HTTPException(status_code=404, detail="Workflow type not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(wf_type, field, value)
    await session.commit()
    await session.refresh(wf_type, attribute_names=["category"])
    return wf_type


# ── User Workflows (configured instances) ────────────────────


@router_workflows.get("/workflows", response_model=list[UserWorkflowListRead])
async def list_workflows(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    # DISTINCT ON (workflow_id) latest run per workflow. Archived runs are
    # excluded so a workflow whose only recent runs were archived shows its
    # most recent VISIBLE run (or none if all are archived).
    latest_runs = (
        select(
            WorkflowRuns.workflow_id,
            WorkflowRuns.run_id.label("latest_run_id"),
            WorkflowRuns.status.label("latest_status"),
            WorkflowRuns.started_at.label("latest_started_at"),
        )
        .where(WorkflowRuns.archived.is_(False))
        .distinct(WorkflowRuns.workflow_id)
        .order_by(WorkflowRuns.workflow_id, WorkflowRuns.started_at.desc())
        .subquery()
    )

    # Artifact count per run (for the latest run's run_id)
    artifact_counts = (
        select(
            WorkflowArtifacts.run_id,
            func.count(WorkflowArtifacts.artifact_id).label("artifact_count"),
        )
        .group_by(WorkflowArtifacts.run_id)
        .subquery()
    )

    result = await session.execute(
        select(
            UserWorkflows,
            latest_runs.c.latest_status,
            latest_runs.c.latest_started_at,
            artifact_counts.c.artifact_count,
        )
        .join(
            latest_runs,
            UserWorkflows.workflow_id == latest_runs.c.workflow_id,
            isouter=True,
        )
        .join(
            artifact_counts,
            latest_runs.c.latest_run_id == artifact_counts.c.run_id,
            isouter=True,
        )
        .options(
            selectinload(UserWorkflows.workflow_type).selectinload(WorkflowTypes.category)
        )
        .where(UserWorkflows.deleted == 0)
        .where(*_run_scope_filter(user))
        .order_by(UserWorkflows.created_at.desc())
    )

    rows = []
    for workflow, latest_status, latest_started_at, artifact_count in result.all():
        # If there is a latest run, artifact_count is 0 when the LEFT JOIN
        # found no artifact rows. If there's no run at all, keep it None.
        if latest_status is None:
            normalized_count = None
        else:
            normalized_count = int(artifact_count or 0)
        rows.append(
            UserWorkflowListRead(
                workflow_id=workflow.workflow_id,
                user_id=workflow.user_id,
                group_id=workflow.group_id,
                type_id=workflow.type_id,
                name=workflow.name,
                schedule=workflow.schedule,
                enabled=workflow.enabled,
                last_run_at=workflow.last_run_at,
                created_at=workflow.created_at,
                type=WorkflowTypeRead.model_validate(workflow.workflow_type),
                latest_run_status=latest_status,
                latest_run_at=latest_started_at,
                latest_run_artifact_count=normalized_count,
            )
        )
    return rows


@router_workflows.post("/workflows", response_model=UserWorkflowRead)
async def create_workflow(
    body: UserWorkflowCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    wf_type = await session.get(WorkflowTypes, body.type_id)
    if not wf_type or not wf_type.enabled:
        raise HTTPException(status_code=404, detail="Workflow type not found")

    config = _normalize_secrets_in_config(body.config, body.type_id)

    workflow = UserWorkflows(
        user_id=user.user_id,
        group_id=user.group_id,
        type_id=body.type_id,
        name=body.name,
        config=config,
        schedule=body.schedule,
        enabled=body.enabled,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


# ── Bulk operations ──────────────────────────────────────────
# Must come BEFORE `/workflows/{workflow_id}` routes so FastAPI matches the
# literal path before the parametric one.


@router_workflows.post("/workflows/bulk-delete")
async def bulk_delete_workflows(
    body: BulkDeleteRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    if not body.workflow_ids:
        return {"deleted_count": 0}

    result = await session.execute(
        update(UserWorkflows)
        .where(UserWorkflows.workflow_id.in_(body.workflow_ids))
        .where(UserWorkflows.group_id == user.group_id)
        .where(UserWorkflows.deleted == 0)
        .values(deleted=1)
    )
    await session.commit()
    return {"deleted_count": result.rowcount or 0}


# ── Single-workflow routes ───────────────────────────────────


async def _get_active_workflow(session: AsyncSession, workflow_id: int, user: User) -> UserWorkflows:
    workflow = await session.get(UserWorkflows, workflow_id)
    if (
        not workflow
        or workflow.group_id != user.group_id
        or workflow.deleted != 0
    ):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


async def _load_workflow_with_type(session: AsyncSession, workflow_id: int, user: User) -> UserWorkflows:
    """Same access guard as _get_active_workflow but eager-loads the type+category."""
    result = await session.execute(
        select(UserWorkflows)
        .options(selectinload(UserWorkflows.workflow_type).selectinload(WorkflowTypes.category))
        .where(UserWorkflows.workflow_id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    if (
        not workflow
        or workflow.group_id != user.group_id
        or workflow.deleted != 0
    ):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


def _serialize_workflow(workflow: UserWorkflows) -> UserWorkflowRead:
    """Serialize a UserWorkflows (with eager-loaded workflow_type) into the read schema."""
    return UserWorkflowRead(
        workflow_id=workflow.workflow_id,
        user_id=workflow.user_id,
        group_id=workflow.group_id,
        type_id=workflow.type_id,
        name=workflow.name,
        config=workflow.config,
        schedule=workflow.schedule,
        enabled=workflow.enabled,
        last_run_at=workflow.last_run_at,
        created_at=workflow.created_at,
        type=WorkflowTypeRead.model_validate(workflow.workflow_type) if workflow.workflow_type else None,
    )


@router_workflows.get("/workflows/{workflow_id}", response_model=UserWorkflowRead)
async def get_workflow(
    workflow_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _load_workflow_with_type(session, workflow_id, user)
    return _serialize_workflow(workflow)


@router_workflows.put("/workflows/{workflow_id}", response_model=UserWorkflowRead)
async def update_workflow(
    workflow_id: int,
    body: UserWorkflowUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _load_workflow_with_type(session, workflow_id, user)
    existing_config = dict(workflow.config) if workflow.config else {}

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "config" and value is not None:
            value = _normalize_secrets_in_config(value, workflow.type_id, existing_config)
        setattr(workflow, field, value)

    await session.commit()
    await session.refresh(workflow, attribute_names=["workflow_type"])
    return _serialize_workflow(workflow)


# ── Schedule listing + preview ──────────────────────────────


class ScheduleListItem(BaseModel):
    workflow_id: int
    workflow_name: str
    user_id: int
    user_email: str
    type_id: int
    type_long_name: str
    enabled: bool
    schedule: dict
    summary: str
    next_fires_utc: list[datetime]
    last_run_at: datetime | None
    last_run_id: int | None
    latest_run_status: str | None


@router_workflows.get("/schedules", response_model=list[ScheduleListItem])
async def list_schedules(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """All scheduled workflows visible to the caller.

    Scope: employees see their own; managers and groupadmins see their
    group; superusers see everything. Includes paused (enabled=false)
    rows so users can resume them from the cockpit.

    `next_fire_utc` is computed server-side so the frontend doesn't
    duplicate the schedule evaluation logic.
    """
    from backend.services.schedule import (
        ScheduleError,
        human_summary,
        next_fires,
        parse_schedule,
    )

    scope = _run_scope_filter(user)

    # Subquery: latest run_id per workflow (any trigger). Left-joined so
    # workflows that have never run still appear in the list with
    # last_run_id=None.
    last_run_subq = (
        select(
            WorkflowRuns.workflow_id.label("wf_id"),
            func.max(WorkflowRuns.run_id).label("last_run_id"),
        )
        .group_by(WorkflowRuns.workflow_id)
        .subquery()
    )

    q = (
        select(
            UserWorkflows,
            User,
            WorkflowTypes,
            last_run_subq.c.last_run_id,
            WorkflowRuns.status.label("latest_run_status"),
        )
        .join(User, UserWorkflows.user_id == User.user_id)
        .join(WorkflowTypes, UserWorkflows.type_id == WorkflowTypes.type_id)
        .outerjoin(last_run_subq, UserWorkflows.workflow_id == last_run_subq.c.wf_id)
        .outerjoin(WorkflowRuns, WorkflowRuns.run_id == last_run_subq.c.last_run_id)
        .where(
            UserWorkflows.deleted == 0,
            UserWorkflows.schedule.isnot(None),
        )
    )
    for clause in scope:
        q = q.where(clause)

    result = await session.execute(q)
    rows = result.all()

    now_utc = datetime.now(timezone.utc)
    items: list[ScheduleListItem] = []
    for wf, owner, wf_type, last_run_id, latest_run_status in rows:
        try:
            s = parse_schedule(wf.schedule)
        except ScheduleError:
            continue
        if s is None:
            continue
        fires = next_fires(s, now_utc, count=5)
        items.append(ScheduleListItem(
            workflow_id=wf.workflow_id,
            workflow_name=wf.name,
            user_id=wf.user_id,
            user_email=owner.email,
            type_id=wf.type_id,
            type_long_name=wf_type.long_name,
            enabled=wf.enabled,
            schedule=wf.schedule,
            summary=human_summary(s),
            next_fires_utc=fires,
            last_run_at=wf.last_run_at,
            last_run_id=last_run_id,
            latest_run_status=latest_run_status,
        ))

    # Sort: enabled with next fire first (soonest fire on top), then
    # enabled but no upcoming fire, then paused at bottom.
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    items.sort(
        key=lambda i: (not i.enabled, i.next_fires_utc[0] if i.next_fires_utc else far_future)
    )
    return items


class SchedulePreviewRequest(BaseModel):
    schedule: dict
    count: int = 5


class SchedulePreviewResponse(BaseModel):
    summary: str
    next_fires_utc: list[datetime]


@router_workflows.post(
    "/workflows/{workflow_id}/schedule/preview",
    response_model=SchedulePreviewResponse,
)
async def preview_schedule(
    workflow_id: int,
    body: SchedulePreviewRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Return a human summary + next N fire times for a candidate schedule.

    Loads the workflow first to enforce ownership (so users can only preview
    schedules against workflows they're allowed to see) but does not mutate
    anything — the candidate schedule never touches the DB.
    """
    await _load_workflow_with_type(session, workflow_id, user)

    from backend.services.schedule import (
        ScheduleError,
        human_summary,
        next_fires,
        parse_schedule,
    )
    try:
        s = parse_schedule(body.schedule)
    except ScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if s is None:
        raise HTTPException(status_code=400, detail="Empty schedule")

    now_utc = datetime.now(timezone.utc)
    fires = next_fires(s, now_utc, count=max(1, min(body.count, 20)))
    return SchedulePreviewResponse(summary=human_summary(s), next_fires_utc=fires)


@router_workflows.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _get_active_workflow(session, workflow_id, user)
    workflow.deleted = 1
    await session.commit()
    return {"detail": "Workflow deleted"}


# ── Workflow Runs ────────────────────────────────────────────


@router_workflows.get("/workflows/{workflow_id}/runs", response_model=list[WorkflowRunRead])
async def list_runs(
    workflow_id: int,
    include_archived: bool = False,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _get_active_workflow(session, workflow_id, user)

    # Archived runs are hidden by default. Superusers can opt in via
    # ?include_archived=true; non-superusers are silently forced to false.
    show_archived = include_archived and user.is_superuser

    artifact_counts = (
        select(
            WorkflowArtifacts.run_id,
            func.count(WorkflowArtifacts.artifact_id).label("artifact_count"),
        )
        .group_by(WorkflowArtifacts.run_id)
        .subquery()
    )

    stmt = (
        select(WorkflowRuns, artifact_counts.c.artifact_count)
        .join(
            artifact_counts,
            WorkflowRuns.run_id == artifact_counts.c.run_id,
            isouter=True,
        )
        .where(WorkflowRuns.workflow_id == workflow_id)
        .order_by(WorkflowRuns.started_at.desc())
        .limit(50)
    )
    if not show_archived:
        stmt = stmt.where(WorkflowRuns.archived.is_(False))
    result = await session.execute(stmt)

    rows = []
    for run, count in result.all():
        rows.append(
            WorkflowRunRead(
                run_id=run.run_id,
                workflow_id=run.workflow_id,
                workflow_name=workflow.name,
                status=run.status,
                current_step=run.current_step,
                total_steps=run.total_steps,
                trigger=run.trigger,
                started_at=run.started_at,
                completed_at=run.completed_at,
                error_detail=run.error_detail,
                artifact_count=int(count or 0),
                config_snapshot=run.config_snapshot,
                archived=run.archived,
            )
        )
    return rows


# ── Trigger a workflow run ───────────────────────────────────

# Single source of truth for workflow type → runner mapping. Adding a new
# workflow type means: write the runner module, add an entry here, ship the
# Alembic data migration that creates the workflow_types row, update the
# create-form's per-type config UI. No other dispatcher branches to find.
WORKFLOW_RUNNERS = {
    1: run_email_monitor,
    2: run_data_analyzer,
    3: run_calendar_digest,
    4: run_sql_runner,
    5: run_email_auto_reply_draft,
    6: run_email_auto_reply_approve,
    7: run_analyze_data_collection,
}


async def _run_workflow_background(workflow_id: int):
    """Run a workflow in the background with its own DB session."""
    async with SqlAsyncSession() as session:
        workflow = await session.get(UserWorkflows, workflow_id)
        if not workflow or workflow.deleted != 0:
            return

        runner = WORKFLOW_RUNNERS.get(workflow.type_id)
        if not runner:
            return

        # Per-workflow run lock (F5): if another run is already active for
        # this workflow_id, skip silently. Covers (a) scheduled fires while a
        # manual run is in flight, (b) manual triggers that slipped past
        # trigger_run's pre-check via a tight race with another trigger.
        # The DB partial unique index from F5.1 is the correctness backstop.
        active_run_id = await session.scalar(
            select(WorkflowRuns.run_id)
            .where(
                WorkflowRuns.workflow_id == workflow_id,
                WorkflowRuns.status.in_(("pending", "running")),
            )
            .limit(1)
        )
        if active_run_id is not None:
            log.info(
                "workflow_run_skipped_already_active",
                workflow_id=workflow_id,
                active_run_id=active_run_id,
            )
            return

        await runner(session, workflow, trigger="manual")


@router_workflows.post("/workflows/{workflow_id}/run", response_model=dict)
async def trigger_run(
    workflow_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _get_active_workflow(session, workflow_id, user)

    if workflow.type_id not in WORKFLOW_RUNNERS:
        raise HTTPException(status_code=400, detail=f"No runner for workflow type {workflow.type_id}")

    # Per-workflow run lock (F5): refuse if an active run already exists.
    # The DB has a partial unique index as the backstop, but the pre-check
    # surfaces a friendly 409 with the existing run_id rather than relying
    # on a constraint violation in the background task.
    active_run_id = await session.scalar(
        select(WorkflowRuns.run_id)
        .where(
            WorkflowRuns.workflow_id == workflow_id,
            WorkflowRuns.status.in_(("pending", "running")),
        )
        .limit(1)
    )
    if active_run_id is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow already running (run #{active_run_id}); refusing to start a duplicate.",
        )

    # Run in background so the API returns immediately
    background_tasks.add_task(_run_workflow_background, workflow_id)

    return {"detail": f"Workflow run triggered for '{workflow.name}'", "workflow_id": workflow_id}


# ── Run details (steps + artifacts) ─────────────────────────


@router_workflows.get("/runs/{run_id}", response_model=WorkflowRunRead)
async def get_run(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id or workflow.deleted != 0:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.archived and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Run not found")

    artifact_count = await session.scalar(
        select(func.count(WorkflowArtifacts.artifact_id)).where(WorkflowArtifacts.run_id == run_id)
    )

    workflow_type = await session.get(WorkflowTypes, workflow.type_id)

    return WorkflowRunRead(
        run_id=run.run_id,
        workflow_id=run.workflow_id,
        workflow_name=workflow.name,
        status=run.status,
        current_step=run.current_step,
        total_steps=run.total_steps,
        trigger=run.trigger,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_detail=run.error_detail,
        artifact_count=int(artifact_count or 0),
        config_snapshot=run.config_snapshot,
        archived=run.archived,
        type_id=workflow.type_id,
        config_schema=workflow_type.config_schema if workflow_type else None,
    )


@router_workflows.get("/runs/{run_id}/steps", response_model=list[WorkflowStepRead])
async def get_run_steps(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id or workflow.deleted != 0:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.archived and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(WorkflowSteps).where(WorkflowSteps.run_id == run_id).order_by(WorkflowSteps.step_number)
    )
    return result.scalars().all()


@router_workflows.get("/runs/{run_id}/artifacts", response_model=list[WorkflowArtifactRead])
async def get_run_artifacts(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    run = await session.get(WorkflowRuns, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id or workflow.deleted != 0:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.archived and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(WorkflowArtifacts).where(WorkflowArtifacts.run_id == run_id).order_by(WorkflowArtifacts.created_at)
    )

    rows = []
    for a in result.scalars().all():
        rows.append(
            WorkflowArtifactRead(
                artifact_id=a.artifact_id,
                run_id=a.run_id,
                step_id=a.step_id,
                file_path=a.file_path,
                file_type=a.file_type,
                file_size=a.file_size,
                description=a.description,
                created_at=a.created_at,
                file_exists=os.path.exists(a.file_path),
            )
        )
    return rows


# ── Email auto-reply approval queue (Variant B) ──────────────


async def _get_pending_reply(
    session: AsyncSession, pending_id: int, user: User
) -> PendingEmailReplies:
    """Fetch a pending reply, enforcing group ownership via the parent workflow."""
    pending = await session.get(PendingEmailReplies, pending_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Pending reply not found")
    workflow = await session.get(UserWorkflows, pending.workflow_id)
    if (
        not workflow
        or workflow.group_id != user.group_id
        or workflow.deleted != 0
    ):
        raise HTTPException(status_code=404, detail="Pending reply not found")
    return pending


@router_workflows.get(
    "/workflows/{workflow_id}/pending-replies",
    response_model=list[PendingEmailReplyRead],
)
async def list_pending_replies(
    workflow_id: int,
    status: str | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """List pending replies for a workflow. Defaults to status='pending' only."""
    await _get_active_workflow(session, workflow_id, user)

    query = (
        select(PendingEmailReplies)
        .where(PendingEmailReplies.workflow_id == workflow_id)
        .order_by(PendingEmailReplies.created_at.desc())
    )
    if status:
        query = query.where(PendingEmailReplies.status == status)
    else:
        query = query.where(PendingEmailReplies.status == "pending")

    result = await session.execute(query)
    return result.scalars().all()


async def _update_log_action(
    session: AsyncSession, pending_id: int, action: str
) -> None:
    """Flip the dedup log's action for this pending_id to the terminal state."""
    result = await session.execute(
        select(EmailAutoReplyLog).where(EmailAutoReplyLog.pending_id == pending_id)
    )
    log_row = result.scalar_one_or_none()
    if log_row is not None:
        log_row.action = action


def _resolve(pending: PendingEmailReplies, status: str, action: str, final_body: str | None) -> None:
    from datetime import datetime, timezone
    pending.status = status
    pending.user_action = action
    pending.final_body = final_body
    pending.resolved_at = datetime.now(timezone.utc)


async def _service_and_gmail_id_for_pending(
    session: AsyncSession, pending: PendingEmailReplies
) -> tuple[str, int | None]:
    """Resolve (service, gmail_account_id) for a pending reply.

    The pending row doesn't carry service info — we look it up from the
    parent workflow's current config. Edge case: if the user changes
    service between queue-time and approve-time, the dispatch uses the
    current config. Acceptable for v1 since changing service while a
    queue is pending is rare and the error path is recoverable.
    """
    workflow = await session.get(UserWorkflows, pending.workflow_id)
    if not workflow:
        # Defensive — referential integrity should prevent this.
        return ("apple_mail", None)
    cfg = workflow.config or {}
    service = (cfg.get("service") or "apple_mail").lower()
    account_id = cfg.get("account_id") if service == "gmail" else None
    return (service, account_id if isinstance(account_id, int) else None)


@router_workflows.post("/pending-replies/{pending_id}/approve")
async def approve_pending_reply(
    pending_id: int,
    body: PendingEmailReplyActionRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Send the reply as-drafted (or the user's lightly-edited body if provided)."""
    pending = await _get_pending_reply(session, pending_id, user)
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already resolved as '{pending.status}'")

    outgoing_body = (body.final_body or pending.body_draft)
    service, gmail_account_id = await _service_and_gmail_id_for_pending(session, pending)
    try:
        if service == "gmail":
            if gmail_account_id is None:
                raise RuntimeError(
                    "workflow.config.account_id is missing — cannot send via Gmail"
                )
            await gmail_client.gmail_send_message(
                session,
                account_id=gmail_account_id,
                to=pending.to_address,
                subject=pending.subject,
                body=outgoing_body,
                workflow_id=pending.workflow_id,
                run_id=pending.run_id,
            )
        else:
            await mcp_client.mail_send_email(
                to=pending.to_address,
                subject=pending.subject,
                body=outgoing_body,
                from_account=pending.source_account,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mail send failed: {str(e)[:200]}")

    action = "edited_and_sent" if body.final_body else "approved_sent"
    _resolve(pending, action, action, body.final_body)
    await _update_log_action(session, pending_id, action)
    await session.commit()
    return {"detail": "sent", "pending_id": pending_id, "status": action}


@router_workflows.post("/pending-replies/{pending_id}/save-draft")
async def save_pending_reply_as_draft(
    pending_id: int,
    body: PendingEmailReplyActionRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Save the (possibly edited) reply to the account's Drafts folder."""
    pending = await _get_pending_reply(session, pending_id, user)
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already resolved as '{pending.status}'")

    outgoing_body = (body.final_body or pending.body_draft)
    service, gmail_account_id = await _service_and_gmail_id_for_pending(session, pending)
    try:
        if service == "gmail":
            if gmail_account_id is None:
                raise RuntimeError(
                    "workflow.config.account_id is missing — cannot save draft via Gmail"
                )
            await gmail_client.gmail_save_draft(
                session,
                account_id=gmail_account_id,
                to=pending.to_address,
                subject=pending.subject,
                body=outgoing_body,
                workflow_id=pending.workflow_id,
                run_id=pending.run_id,
            )
        else:
            await mcp_client.mail_save_draft(
                to=pending.to_address,
                subject=pending.subject,
                body=outgoing_body,
                from_account=pending.source_account,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Draft save failed: {str(e)[:200]}")

    _resolve(pending, "saved_as_draft", "saved_as_draft", body.final_body)
    await _update_log_action(session, pending_id, "saved_as_draft")
    await session.commit()
    return {"detail": "saved_as_draft", "pending_id": pending_id}


@router_workflows.post("/pending-replies/{pending_id}/reject")
async def reject_pending_reply(
    pending_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Reject: no email is sent or saved. Source message stays in the dedup log
    so it won't be re-queued on the next scheduled scan."""
    pending = await _get_pending_reply(session, pending_id, user)
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already resolved as '{pending.status}'")

    _resolve(pending, "rejected", "rejected", None)
    await _update_log_action(session, pending_id, "rejected")
    await session.commit()
    return {"detail": "rejected", "pending_id": pending_id}

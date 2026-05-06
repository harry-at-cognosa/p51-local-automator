import asyncio
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from backend.services import mcp_client
from backend.services.workflows.calendar_digest import run_calendar_digest
from backend.services.workflows.data_analyzer import run_data_analyzer
from backend.services.workflows.email_auto_reply_approve import run_email_auto_reply_approve
from backend.services.workflows.email_auto_reply_draft import run_email_auto_reply_draft
from backend.services.workflows.email_monitor import run_email_monitor
from backend.services.workflows.sql_runner import run_sql_runner

router_workflows = APIRouter()


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
    result = await session.execute(
        select(WorkflowTypes)
        .options(selectinload(WorkflowTypes.category))
        .where(WorkflowTypes.enabled == True)
        .order_by(WorkflowTypes.type_id)
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
    # DISTINCT ON (workflow_id) latest run per workflow
    latest_runs = (
        select(
            WorkflowRuns.workflow_id,
            WorkflowRuns.run_id.label("latest_run_id"),
            WorkflowRuns.status.label("latest_status"),
            WorkflowRuns.started_at.label("latest_started_at"),
        )
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
        .where(UserWorkflows.group_id == user.group_id)
        .where(UserWorkflows.deleted == 0)
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

    workflow = UserWorkflows(
        user_id=user.user_id,
        group_id=user.group_id,
        type_id=body.type_id,
        name=body.name,
        config=body.config,
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

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(workflow, field, value)

    await session.commit()
    await session.refresh(workflow, attribute_names=["workflow_type"])
    return _serialize_workflow(workflow)


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
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _get_active_workflow(session, workflow_id, user)

    artifact_counts = (
        select(
            WorkflowArtifacts.run_id,
            func.count(WorkflowArtifacts.artifact_id).label("artifact_count"),
        )
        .group_by(WorkflowArtifacts.run_id)
        .subquery()
    )

    result = await session.execute(
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
    try:
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
    try:
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

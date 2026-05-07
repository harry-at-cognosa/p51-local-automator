"""Artifact download API — serve generated files to authenticated users."""
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, UserWorkflows, WorkflowArtifacts, WorkflowRuns, WorkflowTypes
from backend.auth.users import current_active_user, fastapi_users, auth_backend


_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename_segment(name: str) -> str:
    """Replace runs of non-safe chars with a single underscore, trim edges."""
    return _FILENAME_UNSAFE.sub("_", name).strip("_") or "artifact"


def _build_download_filename(
    started_at,
    run_id: int,
    workflow_id: int,
    category_id: int,
    type_id: int,
    original_filename: str,
) -> str:
    """Construct YYMMDD_HHMMSS_run_N_uwf_N_cat_N_type_N_<original>.

    Timestamp comes from the run's started_at (local time).
    The original filename is sanitized to keep the prefix readable.

    Exception: AWF-1 polished final reports already carry their own
    user-facing filename (`<slug>_<YYMMDD>_FinalReport.md`); for those
    we hand back the original name verbatim so customers download a
    file named for the report rather than the run metadata. Charts
    and intermediate artifacts keep the standard prefix.
    """
    if original_filename.endswith("_FinalReport.md"):
        # Sanitize the stem only so the .md extension survives.
        stem = _sanitize_filename_segment(original_filename[:-3])
        return f"{stem}.md"
    ts = started_at.strftime("%y%m%d_%H%M%S")
    safe = _sanitize_filename_segment(original_filename)
    return f"{ts}_run_{run_id}_uwf_{workflow_id}_cat_{category_id}_type_{type_id}_{safe}"

router_artifacts = APIRouter()


async def _get_user_from_token(token: str, session: AsyncSession) -> User | None:
    """Validate a JWT token and return the user, or None."""
    try:
        import uuid
        import jwt as pyjwt
        from backend.config import SECRET
        from sqlalchemy import select
        payload = pyjwt.decode(token, SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"])
        user_uuid = payload.get("sub")
        if not user_uuid:
            return None
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_uuid)))
        return result.scalar_one_or_none()
    except Exception:
        return None


@router_artifacts.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: int,
    request: Request,
    token: str | None = Query(None),
    session: AsyncSession = Depends(async_get_session),
):
    # Auth: try query param token first, then standard Bearer header
    user = None
    if token:
        user = await _get_user_from_token(token, session)

    if not user:
        # Fall back to standard auth
        try:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                user = await _get_user_from_token(auth_header[7:], session)
        except Exception:
            pass

    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    artifact = await session.get(WorkflowArtifacts, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = await session.get(WorkflowRuns, artifact.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    workflow = await session.get(UserWorkflows, run.workflow_id)
    if not workflow or workflow.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    workflow_type = await session.get(WorkflowTypes, workflow.type_id)

    if not os.path.isfile(artifact.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    original_filename = os.path.basename(artifact.file_path)
    download_filename = _build_download_filename(
        started_at=run.started_at,
        run_id=run.run_id,
        workflow_id=workflow.workflow_id,
        category_id=workflow_type.category_id if workflow_type else 0,
        type_id=workflow.type_id,
        original_filename=original_filename,
    )

    media_types = {
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "png": "image/png",
        "md": "text/markdown",
    }
    media_type = media_types.get(artifact.file_type, "application/octet-stream")

    return FileResponse(
        artifact.file_path,
        media_type=media_type,
        filename=download_filename,
    )

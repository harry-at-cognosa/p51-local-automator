"""Artifact download API — serve generated files to authenticated users."""
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, UserWorkflows, WorkflowArtifacts, WorkflowRuns
from backend.auth.users import current_active_user, fastapi_users, auth_backend

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

    if not os.path.isfile(artifact.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    filename = os.path.basename(artifact.file_path)
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
        filename=filename,
    )

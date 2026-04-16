"""Artifact download API — serve generated files to authenticated users."""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User, UserWorkflows, WorkflowArtifacts
from backend.auth.users import current_active_user

router_artifacts = APIRouter()


@router_artifacts.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    artifact = await session.get(WorkflowArtifacts, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Check user has access via workflow's group
    from backend.db.models import WorkflowRuns
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

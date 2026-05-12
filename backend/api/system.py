"""System health endpoints — surface server-side config problems to admins.

Currently checks file_system_root validity for the caller's group via
the standard resolution chain (group_settings → api_settings). The
Dashboard banner consumes this on mount for groupadmin+ users so the
"silent run with nothing written" failure mode becomes visible.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.db.models import User
from backend.db.session import async_get_session
from backend.services.path_validator import validate_root_path
from backend.services.workflow_engine import (
    FileSystemRootError,
    _resolve_file_system_root,
)

router_system = APIRouter(prefix="/system")


class HealthCheck(BaseModel):
    ok: bool
    reason: str
    path: str


class HealthResponse(BaseModel):
    file_system_root: HealthCheck


@router_system.get("/health", response_model=HealthResponse)
async def system_health(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Return health status for the caller's group.

    Any authenticated user may call this. The Dashboard banner only
    renders for groupadmin+, but the endpoint itself doesn't gate by
    role — surfacing "your admin needs to fix this" to an employee
    isn't sensitive and may help triage.
    """
    try:
        root = await _resolve_file_system_root(session, user.group_id)
    except FileSystemRootError as e:
        return HealthResponse(
            file_system_root=HealthCheck(ok=False, reason=str(e), path="")
        )

    result = validate_root_path(root)
    return HealthResponse(
        file_system_root=HealthCheck(
            ok=result.ok,
            reason=result.reason,
            path=result.path,
        )
    )

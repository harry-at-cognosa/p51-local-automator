"""Files API — list user-owned input files for the picker UI.

Exposes the per-user inputs sandbox at <file_system_root>/{group_id}/{user_id}/inputs/
to authenticated users. The endpoint is purely read-only; uploads happen
out-of-band via SMB / direct filesystem on the server, then this endpoint
surfaces them to the workflow config UI.

Path-traversal hardening: the `subpath` query param is normalized and the
resolved absolute path must remain inside the user's inputs root. Anything
outside returns 400.
"""
from datetime import datetime, timezone
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_get_session
from backend.db.models import User
from backend.auth.users import current_active_user
from backend.services.workflow_engine import get_user_inputs_dir


router_files = APIRouter(prefix="/files")


class FileEntry(BaseModel):
    name: str
    kind: str           # "file" or "dir"
    size: int | None    # bytes; null for dirs
    modified: str       # ISO 8601 with timezone


class FileListResponse(BaseModel):
    root_path: str
    subpath: str
    entries: list[FileEntry]


def _is_within(parent: str, child: str) -> bool:
    """True if `child` is the same as or inside `parent` (both absolute, normalized)."""
    parent_p = Path(parent).resolve()
    child_p = Path(child).resolve()
    try:
        child_p.relative_to(parent_p)
        return True
    except ValueError:
        return False


def _safe_resolve(root: str, subpath: str) -> str:
    """Join root + subpath and verify the result stays inside root.

    Raises HTTPException(400) on traversal attempts or absolute subpaths.
    """
    if subpath in ("", ".", "/"):
        return root
    # Reject absolute subpaths outright; they would let a client read files
    # outside their inputs sandbox if the join logic ever drifted.
    if os.path.isabs(subpath):
        raise HTTPException(status_code=400, detail="subpath must be relative")
    candidate = os.path.normpath(os.path.join(root, subpath))
    if not _is_within(root, candidate):
        raise HTTPException(status_code=400, detail="subpath escapes inputs root")
    return candidate


@router_files.get("/list", response_model=FileListResponse)
async def list_files(
    subpath: str = Query("", description="Relative path under the user's inputs root"),
    filter_extensions: str | None = Query(
        None,
        description="Comma-separated extensions (e.g. 'csv,xlsx'). Files filtered by these; directories always shown for navigation.",
    ),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """List entries under the authenticated user's inputs sandbox.

    Auto-creates the user's inputs root on first call. Empty results are
    returned as `entries: []` with the resolved path so the frontend can
    show the user where to drop files.
    """
    root = await get_user_inputs_dir(session, user.group_id, user.user_id)
    target = _safe_resolve(root, subpath)

    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Subpath not found")

    allowed_exts: set[str] | None = None
    if filter_extensions:
        allowed_exts = {
            e.strip().lower().lstrip(".")
            for e in filter_extensions.split(",")
            if e.strip()
        } or None

    entries: list[FileEntry] = []
    with os.scandir(target) as it:
        for de in it:
            if de.name.startswith("."):
                continue  # hide dotfiles
            try:
                stat = de.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            if de.is_dir(follow_symlinks=False):
                entries.append(FileEntry(name=de.name, kind="dir", size=None, modified=mtime))
            elif de.is_file(follow_symlinks=False):
                if allowed_exts is not None:
                    ext = de.name.rsplit(".", 1)[-1].lower() if "." in de.name else ""
                    if ext not in allowed_exts:
                        continue
                entries.append(FileEntry(name=de.name, kind="file", size=stat.st_size, modified=mtime))

    entries.sort(key=lambda e: (e.kind != "dir", e.name.lower()))

    return FileListResponse(
        root_path=root,
        subpath=os.path.relpath(target, root) if target != root else "",
        entries=entries,
    )

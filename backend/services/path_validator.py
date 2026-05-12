"""Filesystem root path validation.

Used by:
  - Settings UI (Test button) — validates before save.
  - Workflow engine — validates at run start, raises FileSystemRootError
    on invalid so the run fails visibly instead of silently writing
    to a wrong tree.
  - /system/health endpoint — populates the Dashboard banner for admins.

Pure module: no DB dependency, no I/O beyond a tempfile probe.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass


@dataclass
class PathValidationResult:
    ok: bool
    path: str
    reason: str
    exists: bool
    is_dir: bool
    writable: bool


def validate_root_path(path: str | None) -> PathValidationResult:
    """Validate a filesystem root path.

    Returns a structured result. Never raises. Empty / whitespace-only
    inputs are treated as not-configured.

    "Writable" is verified by creating and removing a tempfile inside
    the directory — `os.access(W_OK)` is unreliable on macOS for paths
    under iCloud / SMB mounts.
    """
    if not path or not path.strip():
        return PathValidationResult(
            ok=False,
            path=path or "",
            reason="file_system_root is not configured",
            exists=False,
            is_dir=False,
            writable=False,
        )

    resolved = os.path.expanduser(path.strip())

    exists = os.path.exists(resolved)
    if not exists:
        return PathValidationResult(
            ok=False,
            path=resolved,
            reason=f"Path does not exist: {resolved}",
            exists=False,
            is_dir=False,
            writable=False,
        )

    is_dir = os.path.isdir(resolved)
    if not is_dir:
        return PathValidationResult(
            ok=False,
            path=resolved,
            reason=f"Path exists but is not a directory: {resolved}",
            exists=True,
            is_dir=False,
            writable=False,
        )

    writable = _probe_writable(resolved)
    if not writable:
        return PathValidationResult(
            ok=False,
            path=resolved,
            reason=f"Directory exists but is not writable: {resolved}",
            exists=True,
            is_dir=True,
            writable=False,
        )

    return PathValidationResult(
        ok=True,
        path=resolved,
        reason="OK",
        exists=True,
        is_dir=True,
        writable=True,
    )


def _probe_writable(directory: str) -> bool:
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".p51_writable_probe_", delete=True
        ):
            pass
        return True
    except (OSError, PermissionError):
        return False

"""Version + deployment-health helpers.

Two responsibilities:

1. Surface what's running. The /api/v1/system/version endpoint pulls
   app_version, db_revision, git_sha, and started_at from here, so a
   curl from any machine answers "what's deployed?" without logging in.

2. Catch deploy skew. check_alembic_alignment() runs once at startup
   and compares the Alembic head on disk (what the code expects) with
   the revision recorded in the DB (what's actually applied). A
   mismatch usually means somebody pulled code without running
   `alembic upgrade head` — the #1 way multi-machine deployments break
   silently.

The helpers cache git_sha and started_at at module load. app_version
is imported from backend.__version__ so there's a single source of
truth.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from backend import __version__
from backend.db.session import sql_sync_engine
from backend.services.logger_service import get_logger

_log = get_logger("version_service")

_STARTED_AT = datetime.now(timezone.utc)


def _detect_git_sha() -> str:
    """Best-effort short git sha. Falls back to 'unknown' on any error
    (e.g., deployment with no .git directory)."""
    try:
        repo_root = Path(__file__).resolve().parents[2]
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode("ascii").strip() or "unknown"
    except Exception:
        return "unknown"


_GIT_SHA = _detect_git_sha()


def _alembic_config() -> Config:
    """Build an Alembic Config pointed at the project's alembic.ini."""
    repo_root = Path(__file__).resolve().parents[2]
    ini_path = repo_root / "alembic.ini"
    cfg = Config(str(ini_path))
    # Make sure script_location resolves regardless of cwd.
    script_location = cfg.get_main_option("script_location") or "backend/alembic"
    if not os.path.isabs(script_location):
        cfg.set_main_option("script_location", str(repo_root / script_location))
    return cfg


def _expected_head() -> str | None:
    try:
        return ScriptDirectory.from_config(_alembic_config()).get_current_head()
    except Exception as exc:
        _log.warning("alembic_head_lookup_failed", error=str(exc))
        return None


def _applied_revision() -> str | None:
    try:
        with sql_sync_engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    except Exception as exc:
        _log.warning("alembic_applied_revision_lookup_failed", error=str(exc))
        return None


async def check_alembic_alignment() -> None:
    """Log a loud warning if the Alembic head on disk does not match
    the revision recorded in the DB. Non-fatal: the app still starts.
    The /version endpoint surfaces the same fields for visual triage."""
    expected = _expected_head()
    applied = _applied_revision()
    if expected and applied and expected == applied:
        _log.info("alembic_aligned", revision=applied)
        return
    _log.warning(
        "alembic_revision_mismatch",
        expected_head=expected,
        applied=applied,
        remedy="run `alembic upgrade head` and restart",
    )


def version_payload() -> dict:
    """Snapshot for the /version endpoint."""
    return {
        "app_version": __version__,
        "db_revision": _applied_revision(),
        "expected_db_revision": _expected_head(),
        "git_sha": _GIT_SHA,
        "started_at": _STARTED_AT.isoformat(),
    }

"""Dual-backend app-password store for the Ad-hoc Email Topic Monitor.

A workflow's `config.storage_method` chooses where its IMAP app
passwords live:

  - "encrypted_db"   → embedded as `app_password_enc` (base64 AES-GCM)
                       per-account inside config.accounts; decrypted on
                       read via backend.services.secrets.

  - "plaintext_file" → stored in `<project_root>/.gmailpasswords.json`
                       at file mode 0600. Key = email address, value =
                       the 16-char app password verbatim. Shared across
                       all workflows on the machine that pick this
                       backend; rows are looked up by email.

The plaintext-file path was explicitly requested by the user (their
threat model: a shell-access attacker already has bigger fish). It
also keeps the feature usable when the TOKEN_ENCRYPTION_KEY env var
isn't set.

Concurrency: writes to the plaintext file use fcntl.flock plus
write-temp-and-rename so two concurrent saves can't clobber each other.

Public surface:
    get_app_password(workflow, email)            → str | None
    save_app_password(workflow, email, password) → None
    clear_for_workflow(workflow)                 → None

`workflow` is a UserWorkflows row — we read `workflow.config` for
storage_method and the per-account encrypted blobs.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Optional

from backend.db.models import UserWorkflows
from backend.services import secrets
from backend.services.logger_service import get_logger

log = get_logger("gmail_password_store")


def _project_root() -> Path:
    """Three parents up from this file (services/ → backend/ → project root)."""
    return Path(__file__).resolve().parents[2]


def _password_file() -> Path:
    return _project_root() / ".gmailpasswords.json"


def _strip(pw: str) -> str:
    """App passwords from Google may include display spaces."""
    return "".join((pw or "").split())


# ── file-backend helpers ─────────────────────────────────────────────


def _load_file_locked() -> dict[str, str]:
    """Read the password file under a shared lock. Returns {} if absent."""
    path = _password_file()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                raw = fh.read() or "{}"
                data = json.loads(raw)
                if not isinstance(data, dict):
                    log.warning("gmailpasswords_file_not_dict", type=type(data).__name__)
                    return {}
                # Coerce values to str; drop non-string entries silently.
                return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception as exc:
            log.warning("gmailpasswords_file_read_failed", error=str(exc))
            return {}


def _write_file_locked(data: dict[str, str]) -> None:
    """Atomic write-with-lock to the password file. mode 0600."""
    path = _password_file()
    tmp_path = path.with_suffix(".tmp")
    # Open the target file for the lock; create it if it doesn't exist yet.
    # We don't use the lock-fd as the write fd because we want write-temp +
    # rename for atomicity.
    lock_path = path
    lock_path.touch(mode=0o600, exist_ok=True)
    with open(lock_path, "r+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            with open(tmp_path, "w", encoding="utf-8") as out_fh:
                json.dump(data, out_fh, indent=2, sort_keys=True)
                out_fh.flush()
                os.fsync(out_fh.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


# ── public surface ───────────────────────────────────────────────────


def get_app_password(workflow: UserWorkflows, email_addr: str) -> Optional[str]:
    """Return the 16-char app password for the given email under this
    workflow's storage method, or None if not present.

    encrypted_db: look up the matching accounts[] entry by email and
    decrypt its `app_password_enc` via secrets.decrypt_from_b64.

    plaintext_file: load .gmailpasswords.json and return data.get(email).
    """
    config = workflow.config or {}
    storage = config.get("storage_method", "encrypted_db")
    if storage == "plaintext_file":
        data = _load_file_locked()
        pw = data.get(email_addr)
        return _strip(pw) if pw else None
    # default → encrypted_db
    for acct in config.get("accounts", []) or []:
        if not isinstance(acct, dict):
            continue
        if acct.get("email") == email_addr and acct.get("service") == "gmail_imap":
            blob = acct.get("app_password_enc")
            if not blob:
                return None
            try:
                return _strip(secrets.decrypt_from_b64(blob))
            except RuntimeError as exc:
                log.warning(
                    "gmail_imap_password_decrypt_failed",
                    email=email_addr,
                    error=str(exc),
                )
                return None
    return None


def save_app_password(
    workflow: UserWorkflows,
    email_addr: str,
    app_password: str,
) -> None:
    """Persist the password according to workflow.config.storage_method.

    For encrypted_db: encrypts the password and writes
    `app_password_enc` into the matching accounts[] entry. The caller
    is responsible for committing the SQLAlchemy session afterward
    (this function mutates `workflow.config` in place).

    For plaintext_file: writes to `.gmailpasswords.json` keyed by email.
    Does NOT touch the workflow row.
    """
    pw = _strip(app_password)
    if not pw:
        return
    config = workflow.config or {}
    storage = config.get("storage_method", "encrypted_db")
    if storage == "plaintext_file":
        data = _load_file_locked()
        data[email_addr] = pw
        _write_file_locked(data)
        return
    # encrypted_db
    enc = secrets.encrypt_to_b64(pw)
    accounts = list(config.get("accounts") or [])
    found = False
    for acct in accounts:
        if not isinstance(acct, dict):
            continue
        if acct.get("email") == email_addr and acct.get("service") == "gmail_imap":
            acct["app_password_enc"] = enc
            found = True
            break
    if not found:
        # Caller hasn't added the account row yet; create it.
        accounts.append({
            "service": "gmail_imap",
            "email": email_addr,
            "app_password_enc": enc,
        })
    config["accounts"] = accounts
    workflow.config = config


def clear_for_workflow(workflow: UserWorkflows) -> None:
    """Wipe stored credentials for every account on this workflow,
    across BOTH backends — encrypted_db blobs in config and any
    matching keys in .gmailpasswords.json. Called by the /clear
    endpoint.

    Mutates `workflow.config` in place; caller commits the session.

    The plaintext-file scrub only removes entries for emails referenced
    by *this* workflow's accounts list. Other workflows' rows in the
    shared file are untouched.
    """
    config = workflow.config or {}
    emails_to_purge: set[str] = set()
    accounts = config.get("accounts") or []
    new_accounts: list[dict] = []
    for acct in accounts:
        if not isinstance(acct, dict):
            new_accounts.append(acct)
            continue
        if acct.get("service") == "gmail_imap":
            email = acct.get("email")
            if isinstance(email, str) and email:
                emails_to_purge.add(email)
            # Drop the row entirely; Clear means clear.
            continue
        new_accounts.append(acct)
    config["accounts"] = new_accounts
    workflow.config = config

    if emails_to_purge:
        data = _load_file_locked()
        before = len(data)
        for email in emails_to_purge:
            data.pop(email, None)
        if len(data) != before:
            _write_file_locked(data)

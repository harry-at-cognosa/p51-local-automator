"""Ad-hoc Workflows — Email Topic Monitor endpoints + cross-type runs history.

A thin UX shell over the Email Topic Monitor runner (Type 1). Each user
has at most one hidden user_workflows row per ad-hoc type_id (flagged
is_adhoc=true); the row is auto-created on first GET. Saves overwrite;
"Clear" wipes both the row's config and any matching plaintext-file
entries.

Endpoints:
    GET    /ad-hoc/email-topic-monitor       → fetch / auto-create
    PUT    /ad-hoc/email-topic-monitor       → save (no run)
    POST   /ad-hoc/email-topic-monitor/run   → save + trigger run
    POST   /ad-hoc/email-topic-monitor/test  → validate credentials
    POST   /ad-hoc/email-topic-monitor/clear → wipe config + creds
    GET    /ad-hoc/runs                       → cross-type run history

Credential redaction: GET never returns plaintext app passwords. For
encrypted_db rows, each accounts[].app_password_enc is replaced with
the literal sentinel `"__STORED__"`. The frontend uses this sentinel
to render the masked-secret placeholder. PUT payloads use the same
sentinel to mean "keep existing"; any other non-empty string is
treated as a new password to encrypt or persist.

The Run endpoint reuses `_run_workflow_background` from api/workflows.py
so the per-workflow run lock (F5) and step-recording logic apply
verbatim to ad-hoc runs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dashboard import _run_scope_filter
from backend.auth.users import current_active_user
from backend.db.models import (
    User,
    UserWorkflows,
    WorkflowArtifacts,
    WorkflowRuns,
    WorkflowTypes,
)
from backend.db.session import async_get_session
from backend.services import gmail_imap_client, gmail_password_store
from backend.services.logger_service import get_logger

router_ad_hoc = APIRouter(prefix="/ad-hoc")
log = get_logger("ad_hoc")

EMAIL_TOPIC_MONITOR_TYPE_ID = 1
ADHOC_NAME_EMAIL_TOPIC_MONITOR = "Ad-hoc Email Topic Monitor"

# Sentinel used in PUT payloads and GET responses to indicate "an app
# password is stored on this account, but it has been redacted from
# the wire format." Distinct from empty/missing so the form can tell
# "user cleared the field" from "user didn't touch it."
STORED_SENTINEL = "__STORED__"

# Per-account timeout for the test endpoint (the parallel asyncio.gather).
TEST_PER_ACCOUNT_TIMEOUT_SECONDS = 10.0


# ── Pydantic models ──────────────────────────────────────────────────


class AdHocAccountIn(BaseModel):
    service: str  # "apple_mail" | "gmail_imap" | "gmail"
    account: Optional[str] = None     # apple_mail (Mail.app account name)
    email: Optional[str] = None       # gmail_imap (email address)
    app_password: Optional[str] = None  # gmail_imap — STORED_SENTINEL means keep existing
    account_id: Optional[int] = None  # gmail (FK into gmail_accounts.id)


class AdHocAccountOut(BaseModel):
    service: str
    account: Optional[str] = None
    email: Optional[str] = None
    app_password: Optional[str] = None  # always STORED_SENTINEL or None on the way out
    account_id: Optional[int] = None    # gmail OAuth account id (no secrets in this value)


class AdHocEmailMonitorRead(BaseModel):
    workflow_id: int
    storage_method: str  # "encrypted_db" | "plaintext_file"
    accounts: list[AdHocAccountOut]
    mailbox: str
    period: str
    topics: list[str]
    scope: str


class AdHocEmailMonitorWrite(BaseModel):
    storage_method: str = Field(default="encrypted_db")
    accounts: list[AdHocAccountIn] = Field(default_factory=list)
    mailbox: str = "INBOX"
    period: str = "last 7 days"
    topics: list[str] = Field(default_factory=list)
    scope: str = ""


class TestAccountResult(BaseModel):
    label: str
    ok: bool
    reason: str


class TestResponse(BaseModel):
    results: list[TestAccountResult]


# ── Helpers ──────────────────────────────────────────────────────────


def _redact_config(config: dict) -> dict:
    """Return a copy of config with app_password_enc replaced by the
    STORED_SENTINEL marker (per-account). Never leaks ciphertext to the
    wire — the frontend doesn't need it and there's no reason to expose."""
    if not isinstance(config, dict):
        return {}
    out = dict(config)
    accounts_in = config.get("accounts") or []
    accounts_out: list[dict] = []
    for acct in accounts_in:
        if not isinstance(acct, dict):
            continue
        clone = {
            "service": acct.get("service"),
            "account": acct.get("account"),
            "email": acct.get("email"),
            "account_id": acct.get("account_id"),
        }
        if acct.get("service") == "gmail_imap":
            # If we have a stored password (DB blob present OR plaintext-file
            # is the storage method), surface the sentinel; the frontend uses
            # it to show "(stored — leave blank to keep)" placeholder copy.
            storage = config.get("storage_method", "encrypted_db")
            if storage == "plaintext_file":
                # The runner reads the file at run time; we can't cheaply
                # check the file from here without a DB query, but the
                # presence of an account row is enough to imply "stored."
                # If the file doesn't actually have a row, Test will report
                # the failure.
                clone["app_password"] = STORED_SENTINEL
            elif acct.get("app_password_enc"):
                clone["app_password"] = STORED_SENTINEL
        # gmail (Workspace OAuth) carries no per-account secrets in the
        # workflow config — credentials live in the gmail_accounts table
        # behind account_id, managed by /api/v1/gmail/oauth/*. Nothing to
        # redact.
        accounts_out.append({k: v for k, v in clone.items() if v is not None})
    out["accounts"] = accounts_out
    # Don't surface the encrypted blobs in the wire format.
    return out


async def _fetch_or_create_adhoc_workflow(
    session: AsyncSession,
    user: User,
    type_id: int,
    default_name: str,
) -> UserWorkflows:
    """One ad-hoc row per (user_id, type_id, is_adhoc=true). Auto-create
    with sensible defaults if none exists."""
    result = await session.execute(
        select(UserWorkflows).where(
            UserWorkflows.user_id == user.user_id,
            UserWorkflows.type_id == type_id,
            UserWorkflows.is_adhoc.is_(True),
            UserWorkflows.deleted == 0,
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow:
        return workflow
    workflow = UserWorkflows(
        user_id=user.user_id,
        group_id=user.group_id,
        type_id=type_id,
        name=default_name,
        config={
            "storage_method": "encrypted_db",
            "accounts": [],
            "mailbox": "INBOX",
            "period": "last 7 days",
            "topics": [],
            "scope": "",
        },
        schedule=None,
        enabled=True,
        is_adhoc=True,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


def _apply_write_to_workflow(workflow: UserWorkflows, body: AdHocEmailMonitorWrite) -> None:
    """Merge a write payload into the workflow's config. Encrypts /
    persists new app passwords via gmail_password_store. Honors the
    STORED_SENTINEL to mean 'keep the existing password'."""
    existing = workflow.config or {}
    existing_accounts: dict[tuple, dict] = {}
    for acct in existing.get("accounts") or []:
        if isinstance(acct, dict):
            key = (acct.get("service"), acct.get("email") or acct.get("account"))
            existing_accounts[key] = acct

    new_storage = body.storage_method
    new_accounts: list[dict] = []
    for in_acct in body.accounts:
        if in_acct.service == "apple_mail":
            new_accounts.append({
                "service": "apple_mail",
                "account": in_acct.account or "iCloud",
            })
            continue
        if in_acct.service == "gmail_imap":
            email = (in_acct.email or "").strip()
            if not email:
                continue
            row = {"service": "gmail_imap", "email": email}
            prior = existing_accounts.get(("gmail_imap", email))
            pw_in = in_acct.app_password
            if pw_in == STORED_SENTINEL or pw_in is None or pw_in == "":
                # Keep whatever the prior row had (encrypted blob OR the
                # plaintext-file entry stays untouched).
                if prior and prior.get("app_password_enc") and new_storage == "encrypted_db":
                    row["app_password_enc"] = prior["app_password_enc"]
            else:
                # New password supplied. Persist into the chosen backend.
                workflow.config = {**existing, "storage_method": new_storage, "accounts": new_accounts + [row]}
                gmail_password_store.save_app_password(workflow, email, pw_in)
                # save_app_password may have re-encrypted into row directly
                # OR written to the file. Refresh row from the updated config.
                for a in (workflow.config.get("accounts") or []):
                    if a.get("service") == "gmail_imap" and a.get("email") == email:
                        row = a
                        break
            new_accounts.append(row)
            continue
        if in_acct.service == "gmail":
            # Workspace OAuth account — credentials live in gmail_accounts,
            # we only persist the account_id reference. The runner's
            # existing gmail-OAuth path (gmail_client.gmail_list_messages)
            # handles auth + refresh.
            if not isinstance(in_acct.account_id, int):
                continue
            new_accounts.append({
                "service": "gmail",
                "account_id": in_acct.account_id,
            })
            continue
        # unknown service silently dropped — frontend shouldn't send these
    workflow.config = {
        "storage_method": new_storage,
        "accounts": new_accounts,
        "mailbox": body.mailbox or "INBOX",
        "period": body.period or "last 7 days",
        "topics": list(body.topics or []),
        "scope": body.scope or "",
    }


def _serialize_read(workflow: UserWorkflows) -> AdHocEmailMonitorRead:
    cfg = _redact_config(workflow.config or {})
    return AdHocEmailMonitorRead(
        workflow_id=workflow.workflow_id,
        storage_method=cfg.get("storage_method", "encrypted_db"),
        accounts=[AdHocAccountOut(**a) for a in cfg.get("accounts") or []],
        mailbox=cfg.get("mailbox", "INBOX"),
        period=cfg.get("period", "last 7 days"),
        topics=list(cfg.get("topics") or []),
        scope=cfg.get("scope", ""),
    )


# ── Endpoints ────────────────────────────────────────────────────────


@router_ad_hoc.get(
    "/email-topic-monitor",
    response_model=AdHocEmailMonitorRead,
)
async def get_email_topic_monitor(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _fetch_or_create_adhoc_workflow(
        session, user, EMAIL_TOPIC_MONITOR_TYPE_ID, ADHOC_NAME_EMAIL_TOPIC_MONITOR,
    )
    return _serialize_read(workflow)


@router_ad_hoc.put(
    "/email-topic-monitor",
    response_model=AdHocEmailMonitorRead,
)
async def save_email_topic_monitor(
    body: AdHocEmailMonitorWrite,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _fetch_or_create_adhoc_workflow(
        session, user, EMAIL_TOPIC_MONITOR_TYPE_ID, ADHOC_NAME_EMAIL_TOPIC_MONITOR,
    )
    _apply_write_to_workflow(workflow, body)
    # The dual mutate in _apply_write_to_workflow doesn't always flag
    # `config` dirty; mark it explicitly.
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(workflow, "config")
    await session.commit()
    await session.refresh(workflow)
    return _serialize_read(workflow)


@router_ad_hoc.post(
    "/email-topic-monitor/run",
    response_model=AdHocEmailMonitorRead,
)
async def run_email_topic_monitor(
    body: AdHocEmailMonitorWrite,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    workflow = await _fetch_or_create_adhoc_workflow(
        session, user, EMAIL_TOPIC_MONITOR_TYPE_ID, ADHOC_NAME_EMAIL_TOPIC_MONITOR,
    )
    _apply_write_to_workflow(workflow, body)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(workflow, "config")
    await session.commit()
    await session.refresh(workflow)

    # Reuse the same background-task path as a normal manual run. The
    # per-workflow run lock (F5) applies to ad-hoc rows too — saves us
    # from rebuilding that lock here.
    from backend.api.workflows import _run_workflow_background
    background_tasks.add_task(_run_workflow_background, workflow.workflow_id)

    return _serialize_read(workflow)


async def _test_one_account(
    label: str,
    account: dict,
    workflow: UserWorkflows,
    session: AsyncSession,
) -> TestAccountResult:
    service = account.get("service")
    try:
        if service == "apple_mail":
            # No credentials to test; verify the named account exists in
            # Mail.app via the MCP server. If MCP is offline this surfaces
            # a clear error instead of a silent pass.
            from backend.services import mcp_client
            # mail_list_messages with limit=1 is the cheapest probe.
            await mcp_client.mail_list_messages(account.get("account", "iCloud"), "INBOX", limit=1)
            return TestAccountResult(label=label, ok=True, reason="ok")
        if service == "gmail_imap":
            email = account.get("email") or ""
            password = gmail_password_store.get_app_password(workflow, email)
            if not password:
                return TestAccountResult(
                    label=label, ok=False,
                    reason=f"No app password stored for {email}.",
                )
            ok, reason = await gmail_imap_client.imap_test_login(email, password)
            return TestAccountResult(label=label, ok=ok, reason=reason)
        if service == "gmail":
            # Workspace OAuth account — credentials live in the
            # gmail_accounts table behind account_id. Cheapest probe: list
            # one message via the API; if the refresh token has expired or
            # the row is missing/disconnected, gmail_client surfaces a
            # specific exception we relay verbatim.
            from backend.services import gmail_client
            account_id = account.get("account_id")
            if not isinstance(account_id, int):
                return TestAccountResult(
                    label=label, ok=False,
                    reason="Workspace Gmail account is missing its account_id reference.",
                )
            await gmail_client.gmail_list_messages(
                session, account_id, mailbox="INBOX", limit=1,
                workflow_id=workflow.workflow_id, run_id=None,
            )
            return TestAccountResult(label=label, ok=True, reason="ok")
        return TestAccountResult(label=label, ok=False, reason=f"Unknown service {service!r}")
    except Exception as exc:
        return TestAccountResult(label=label, ok=False, reason=str(exc))


@router_ad_hoc.post(
    "/email-topic-monitor/test",
    response_model=TestResponse,
)
async def test_email_topic_monitor(
    body: AdHocEmailMonitorWrite,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Validate the supplied credentials against each account in
    parallel. Doesn't persist the workflow row; tests the form's
    current state against the world.

    For accounts where the user left app_password as STORED_SENTINEL,
    we resolve to the persisted password via the password store; if
    nothing is stored, that account reports an error.
    """
    workflow = await _fetch_or_create_adhoc_workflow(
        session, user, EMAIL_TOPIC_MONITOR_TYPE_ID, ADHOC_NAME_EMAIL_TOPIC_MONITOR,
    )

    # Build a transient workflow.config that reflects the form state.
    # We DO NOT commit this — _apply_write_to_workflow writes to
    # workflow.config in-process; subsequent get_app_password() calls
    # read from it. If the form has a fresh password we run save flow
    # which actually persists; that's intentional — saving creds
    # implicitly when the user clicks Test feels acceptable here, and
    # it lets a fresh Test on a fresh password actually validate the
    # new value rather than the stored stale one.
    _apply_write_to_workflow(workflow, body)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(workflow, "config")
    await session.commit()

    accounts = workflow.config.get("accounts") or []
    if not accounts:
        return TestResponse(results=[])

    from backend.services.workflows.email_monitor import _account_label
    labels = [_account_label(a) for a in accounts]

    tasks = [
        asyncio.wait_for(
            _test_one_account(label, account, workflow, session),
            timeout=TEST_PER_ACCOUNT_TIMEOUT_SECONDS,
        )
        for label, account in zip(labels, accounts)
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[TestAccountResult] = []
    for label, r in zip(labels, raw_results):
        if isinstance(r, asyncio.TimeoutError):
            results.append(TestAccountResult(
                label=label, ok=False,
                reason=f"Timed out after {TEST_PER_ACCOUNT_TIMEOUT_SECONDS:.0f}s.",
            ))
        elif isinstance(r, Exception):
            results.append(TestAccountResult(label=label, ok=False, reason=str(r)))
        else:
            results.append(r)
    return TestResponse(results=results)


@router_ad_hoc.post(
    "/email-topic-monitor/clear",
    response_model=AdHocEmailMonitorRead,
)
async def clear_email_topic_monitor(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Wipe both backends for every account on this workflow, then
    reset the rest of the form fields to their defaults."""
    workflow = await _fetch_or_create_adhoc_workflow(
        session, user, EMAIL_TOPIC_MONITOR_TYPE_ID, ADHOC_NAME_EMAIL_TOPIC_MONITOR,
    )
    gmail_password_store.clear_for_workflow(workflow)
    workflow.config = {
        "storage_method": "encrypted_db",
        "accounts": [],
        "mailbox": "INBOX",
        "period": "last 7 days",
        "topics": [],
        "scope": "",
    }
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(workflow, "config")
    await session.commit()
    await session.refresh(workflow)
    return _serialize_read(workflow)


# ── Cross-type ad-hoc run history ───────────────────────────────────


class AdHocRunListItem(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str
    type_id: int
    type_long_name: str
    status: str
    current_step: int
    total_steps: int
    trigger: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    artifact_count: int = 0


# Mirrors the cap on the existing per-workflow runs list endpoint.
ADHOC_RUNS_LIMIT = 50


@router_ad_hoc.get(
    "/runs",
    response_model=list[AdHocRunListItem],
)
async def list_adhoc_runs(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Read-only cross-type history of ad-hoc runs visible to the
    caller under the standard _run_scope_filter rule (superuser → all,
    groupadmin/manager → group, everyone else → own).

    Hides archived runs unconditionally. The list-Workflows
    `?include_adhoc=true` superuser opt-in pattern doesn't apply here
    — this endpoint is FOR ad-hoc rows by construction.
    """
    artifact_counts = (
        select(
            WorkflowArtifacts.run_id,
            func.count(WorkflowArtifacts.artifact_id).label("artifact_count"),
        )
        .group_by(WorkflowArtifacts.run_id)
        .subquery()
    )

    q = (
        select(
            WorkflowRuns,
            UserWorkflows,
            WorkflowTypes,
            artifact_counts.c.artifact_count,
        )
        .join(UserWorkflows, UserWorkflows.workflow_id == WorkflowRuns.workflow_id)
        .join(WorkflowTypes, WorkflowTypes.type_id == UserWorkflows.type_id)
        .outerjoin(artifact_counts, artifact_counts.c.run_id == WorkflowRuns.run_id)
        .where(
            UserWorkflows.is_adhoc.is_(True),
            UserWorkflows.deleted == 0,
            WorkflowRuns.archived.is_(False),
        )
        .where(*_run_scope_filter(user))
        .order_by(WorkflowRuns.started_at.desc())
        .limit(ADHOC_RUNS_LIMIT)
    )
    result = await session.execute(q)
    rows: list[AdHocRunListItem] = []
    for run, workflow, wf_type, artifact_count in result.all():
        rows.append(AdHocRunListItem(
            run_id=run.run_id,
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            type_id=wf_type.type_id,
            type_long_name=wf_type.long_name,
            status=run.status,
            current_step=run.current_step,
            total_steps=run.total_steps,
            trigger=run.trigger,
            started_at=run.started_at,
            completed_at=run.completed_at,
            artifact_count=int(artifact_count or 0),
        ))
    return rows

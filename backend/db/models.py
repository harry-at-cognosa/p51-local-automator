from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON,
    LargeBinary, Text, VARCHAR,
    CheckConstraint, UniqueConstraint,
    func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


# ── Tenant / Auth tables (adapted from CompIntelMon) ──────────────


class ApiGroups(Base):
    __tablename__ = "api_groups"

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deleted: Mapped[int] = mapped_column(Integer, index=True, nullable=False, server_default=text("0"))
    group_name: Mapped[str] = mapped_column(VARCHAR, nullable=False, server_default=text("'Undefined group'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'TRUE'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    api_users_list: Mapped[list["User"]] = relationship("User", back_populates="group")
    group_settings_list: Mapped[list["GroupSettings"]] = relationship("GroupSettings", back_populates="group")


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "api_users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deleted: Mapped[int] = mapped_column(Integer, index=True, nullable=False, server_default=text("0"))
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_groups.group_id", name="fk_api_users_group_id"),
        nullable=False,
        server_default=text("2"),
    )
    user_name: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(VARCHAR, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_groupadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'FALSE'"))
    # Roles: is_superuser (from fastapi-users), is_groupadmin, is_manager
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'FALSE'"))

    group: Mapped["ApiGroups"] = relationship("ApiGroups", back_populates="api_users_list")
    workflows: Mapped[list["UserWorkflows"]] = relationship("UserWorkflows", back_populates="user")

    if TYPE_CHECKING:
        id: uuid.UUID
    else:
        id: Mapped[uuid.UUID] = mapped_column(GUID, unique=True, default=uuid.uuid4)

    __table_args__ = (
        UniqueConstraint("user_name", name="uq_api_users_user_name"),
        CheckConstraint(
            "char_length(user_name) BETWEEN 3 AND 32 AND user_name ~ '^[a-z0-9_-]+$'",
            name="ck_api_users_user_name_format",
        ),
    )


class ApiSettings(Base):
    __tablename__ = "api_settings"

    name: Mapped[str] = mapped_column(VARCHAR, primary_key=True)
    value: Mapped[str] = mapped_column(VARCHAR, nullable=False)


class GroupSettings(Base):
    __tablename__ = "group_settings"

    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_groups.group_id", name="fk_group_settings_group_id"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(VARCHAR, primary_key=True)
    value: Mapped[str] = mapped_column(VARCHAR, nullable=False)

    group: Mapped["ApiGroups"] = relationship("ApiGroups", back_populates="group_settings_list")


# ── Workflow tables (new for this project) ──────────────────────


class WorkflowCategories(Base):
    """Top-level groupings for workflow types (seeded; no CRUD UI)."""
    __tablename__ = "workflow_categories"

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_key: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, unique=True)
    short_name: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    long_name: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'TRUE'"))

    workflow_types: Mapped[list["WorkflowTypes"]] = relationship("WorkflowTypes", back_populates="category")


class WorkflowTypes(Base):
    """Catalog of available automation types (seeded at startup)."""
    __tablename__ = "workflow_types"

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type_name: Mapped[str] = mapped_column(VARCHAR(64), nullable=False, unique=True)
    type_desc: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_categories.category_id", name="fk_workflow_types_category_id"),
        nullable=False,
    )
    short_name: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    long_name: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    default_config: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    required_services: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    # Optional list of field descriptors that drive the schema-driven config form
    # for new workflow types. Existing types 1–6 keep their hand-tuned forms;
    # this is the path forward for new types. See the populating migration for
    # the schema shape.
    config_schema: Mapped[list | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'TRUE'"))
    # Whether instances of this type can be scheduled. AWF-1 (Analyze Data
    # Collection) is false: a single run is too expensive/slow to dispatch
    # from cron. Frontend hides schedule UI when this is false.
    schedulable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'TRUE'"))

    category: Mapped["WorkflowCategories"] = relationship("WorkflowCategories", back_populates="workflow_types")
    user_workflows: Mapped[list["UserWorkflows"]] = relationship("UserWorkflows", back_populates="workflow_type")


class UserWorkflows(Base):
    """User-configured workflow instances."""
    __tablename__ = "user_workflows"

    workflow_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_users.user_id", name="fk_user_workflows_user_id"),
        nullable=False,
    )
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_groups.group_id", name="fk_user_workflows_group_id"),
        nullable=False,
    )
    type_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_types.type_id", name="fk_user_workflows_type_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("'TRUE'"))
    deleted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="workflows")
    workflow_type: Mapped["WorkflowTypes"] = relationship("WorkflowTypes", back_populates="user_workflows")
    runs: Mapped[list["WorkflowRuns"]] = relationship("WorkflowRuns", back_populates="workflow")


class WorkflowRuns(Base):
    """Execution history for workflow runs."""
    __tablename__ = "workflow_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user_workflows.workflow_id", name="fk_workflow_runs_workflow_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'pending'"))
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    trigger: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'manual'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Captured at run start from user_workflows.config. NULL for runs created
    # before the column existed (no authoritative source to backfill).
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set TRUE by the archive sweep (Phase M). Hides the run from non-superuser
    # views without removing data. Purge sweep hard-deletes regardless.
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    workflow: Mapped["UserWorkflows"] = relationship("UserWorkflows", back_populates="runs")
    steps: Mapped[list["WorkflowSteps"]] = relationship("WorkflowSteps", back_populates="run")
    artifacts: Mapped[list["WorkflowArtifacts"]] = relationship("WorkflowArtifacts", back_populates="run")


class WorkflowSteps(Base):
    """Per-step results within a workflow run."""
    __tablename__ = "workflow_steps"

    step_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_runs.run_id", name="fk_workflow_steps_run_id"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'pending'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Agentic-engine annotations. NULL for steps from types 1–6.
    # stage ∈ {ingest, profile, analyze, synthesize, audit, scribe}
    # kind  ∈ {skill_call, llm_turn, stage_marker}
    stage: Mapped[str | None] = mapped_column(VARCHAR, nullable=True)
    kind: Mapped[str | None] = mapped_column(VARCHAR, nullable=True)

    run: Mapped["WorkflowRuns"] = relationship("WorkflowRuns", back_populates="steps")


class WorkflowArtifacts(Base):
    """Generated files from workflow runs."""
    __tablename__ = "workflow_artifacts"

    artifact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_runs.run_id", name="fk_workflow_artifacts_run_id"),
        nullable=False,
    )
    step_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("workflow_steps.step_id", name="fk_workflow_artifacts_step_id"),
        nullable=True,
    )
    file_path: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    file_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    description: Mapped[str] = mapped_column(VARCHAR, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped["WorkflowRuns"] = relationship("WorkflowRuns", back_populates="artifacts")


# ── Conversations (from CompIntelMon) ──────────────────────────


class Conversations(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user_workflows.workflow_id", name="fk_conversations_workflow_id"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_users.user_id", name="fk_conversations_user_id"),
        nullable=False,
    )
    conversation_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'query'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[list["ConversationMessages"]] = relationship("ConversationMessages", back_populates="conversation")


class ConversationMessages(Base):
    __tablename__ = "conversation_messages"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversations.conversation_id", name="fk_conv_messages_conversation_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'complete'"))
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation: Mapped["Conversations"] = relationship("Conversations", back_populates="messages")


class PendingEmailReplies(Base):
    """Variant-B approval queue: per-message pending reply state."""
    __tablename__ = "pending_email_replies"

    pending_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user_workflows.workflow_id", name="fk_pending_replies_workflow_id"),
        nullable=False,
    )
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_runs.run_id", name="fk_pending_replies_run_id"),
        nullable=False,
    )
    source_message_id: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    source_account: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    source_mailbox: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    source_from: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    source_subject: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    to_address: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    subject: Mapped[str] = mapped_column(VARCHAR, nullable=False)
    body_draft: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | approved_sent | edited_and_sent | saved_as_draft | rejected
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'pending'"))
    user_action: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    final_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailAutoReplyLog(Base):
    """Dedup ledger so scheduled runs don't acknowledge the same message twice.

    Unique on (workflow_id, source_message_id). `action` is one of:
    'draft_saved', 'sent_direct', 'queued_for_approval', plus terminal states
    (updated after user resolves a queued reply).
    """
    __tablename__ = "email_auto_reply_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user_workflows.workflow_id", name="fk_auto_reply_log_workflow_id"),
        nullable=False,
    )
    source_message_id: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    source_account: Mapped[str] = mapped_column(VARCHAR(128), nullable=False)
    action: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    pending_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("pending_email_replies.pending_id", name="fk_auto_reply_log_pending_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workflow_id", "source_message_id", name="uq_auto_reply_log_workflow_msg"),
    )


class GmailAccounts(Base):
    """Per-user OAuth-connected Gmail accounts (Track B Phase B1).

    Refresh and access tokens are encrypted at rest via
    backend/services/secrets.py (AES-GCM). status tracks the lifecycle:
    'active' | 'disconnected' (refresh token revoked at Google) | 'revoked'
    (user-initiated revoke).
    """
    __tablename__ = "gmail_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_users.user_id", name="fk_gmail_accounts_user_id"),
        nullable=False,
    )
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_groups.group_id", name="fk_gmail_accounts_group_id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    refresh_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    access_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_gmail_accounts_user_email"),
    )


class GmailTokenUsage(Base):
    """Append-only audit log of Gmail API calls and OAuth lifecycle events.

    workflow_id and run_id are nullable because OAuth events (connect,
    refresh, revoke) fire outside any workflow context.
    """
    __tablename__ = "gmail_token_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("gmail_accounts.id", name="fk_gmail_token_usage_account_id"),
        nullable=False,
    )
    workflow_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaintenanceLog(Base):
    """Append-only audit row per non-dry-run archive/purge sweep (Phase M).

    Dry-runs do not write rows; only commits do. Bytes_freed is only
    meaningful for purge (NULL for archive, since archive does not touch
    disk). Error_detail captures the first ~1000 chars of an exception if
    a sweep failed partway; counts still reflect what was processed
    before the failure.
    """
    __tablename__ = "maintenance_log"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(VARCHAR(16), nullable=False)  # 'archive' | 'purge'
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("api_users.user_id", name="fk_maintenance_log_user_id"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(VARCHAR(16), nullable=False)  # 'all' | 'group'
    scope_group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("api_groups.group_id", name="fk_maintenance_log_group_id"),
        nullable=True,
    )
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workflows_affected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    runs_affected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    steps_affected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    artifacts_affected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    bytes_freed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

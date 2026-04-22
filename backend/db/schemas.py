import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, Field, field_validator


# ── User schemas (fastapi-users) ─────────────────────────────


class UserRead(schemas.BaseUser[uuid.UUID]):
    user_id: int
    group_id: int
    user_name: str
    full_name: str
    is_groupadmin: bool = False
    is_manager: bool = False
    created_at: datetime | None = None


class UserCreate(schemas.BaseUserCreate):
    user_id: int | None = None
    group_id: int
    user_name: str = Field(..., min_length=3, max_length=32)
    full_name: str = ""
    is_groupadmin: bool = False
    is_manager: bool = False

    @field_validator("user_name")
    @classmethod
    def validate_user_name(cls, v: str) -> str:
        import re
        v = v.lower()
        if not re.match(r"^[a-z0-9_-]+$", v):
            raise ValueError("user_name must contain only lowercase letters, numbers, underscores, or hyphens")
        return v


class UserUpdate(schemas.BaseUserUpdate):
    user_name: str | None = None
    full_name: str | None = None
    group_id: int | None = None
    is_groupadmin: bool | None = None
    is_manager: bool | None = None


class UsersMe(BaseModel):
    id: uuid.UUID
    user_id: int
    group_id: int
    group_name: str
    email: str
    user_name: str
    full_name: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    is_groupadmin: bool
    is_manager: bool


# ── User management schemas ──────────────────────────────────


class UserManageRead(BaseModel):
    user_id: int
    group_id: int
    email: str
    user_name: str
    full_name: str
    is_active: bool
    is_superuser: bool
    is_groupadmin: bool
    is_manager: bool
    created_at: datetime | None = None
    last_seen: datetime | None = None

    class Config:
        from_attributes = True


class UserManageCreate(BaseModel):
    group_id: int
    email: str
    user_name: str = Field(..., min_length=3, max_length=32)
    full_name: str = ""
    password: str = Field(..., min_length=4)
    is_active: bool = True
    is_superuser: bool = False
    is_groupadmin: bool = False
    is_manager: bool = False

    @field_validator("user_name")
    @classmethod
    def validate_user_name(cls, v: str) -> str:
        import re
        v = v.lower()
        if not re.match(r"^[a-z0-9_-]+$", v):
            raise ValueError("user_name must contain only lowercase letters, numbers, underscores, or hyphens")
        return v


class UserManageUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    password: str | None = None
    group_id: int | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    is_groupadmin: bool | None = None
    is_manager: bool | None = None


# ── Workflow schemas ─────────────────────────────────────────


class WorkflowCategoryRead(BaseModel):
    category_id: int
    category_key: str
    short_name: str
    long_name: str
    sort_order: int
    enabled: bool

    class Config:
        from_attributes = True


class WorkflowTypeRead(BaseModel):
    type_id: int
    type_name: str
    type_desc: str
    short_name: str
    long_name: str
    category: WorkflowCategoryRead
    default_config: dict
    required_services: list | dict
    enabled: bool

    class Config:
        from_attributes = True


class UserWorkflowCreate(BaseModel):
    type_id: int
    name: str
    config: dict = {}
    schedule: dict | None = None
    enabled: bool = True


class UserWorkflowRead(BaseModel):
    workflow_id: int
    user_id: int
    group_id: int
    type_id: int
    name: str
    config: dict
    schedule: dict | None
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserWorkflowListRead(BaseModel):
    """List-page row: adds nested type (with category) and latest-run status."""
    workflow_id: int
    user_id: int
    group_id: int
    type_id: int
    name: str
    schedule: dict | None
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime
    type: WorkflowTypeRead
    latest_run_status: str | None
    latest_run_at: datetime | None
    latest_run_artifact_count: int | None

    class Config:
        from_attributes = True


class UserWorkflowUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    schedule: dict | None = None
    enabled: bool | None = None


class BulkDeleteRequest(BaseModel):
    workflow_ids: list[int]


class WorkflowRunRead(BaseModel):
    run_id: int
    workflow_id: int
    status: str
    current_step: int
    total_steps: int
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    error_detail: str | None
    artifact_count: int = 0

    class Config:
        from_attributes = True


class WorkflowStepRead(BaseModel):
    step_id: int
    run_id: int
    step_number: int
    step_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    output_summary: str | None
    artifacts: dict | None
    llm_tokens_used: int
    error_detail: str | None

    class Config:
        from_attributes = True


class WorkflowArtifactRead(BaseModel):
    artifact_id: int
    run_id: int
    step_id: int | None
    file_path: str
    file_type: str
    file_size: int
    description: str
    created_at: datetime
    file_exists: bool = True

    class Config:
        from_attributes = True


# ── Email auto-reply ─────────────────────────────────────────


class PendingEmailReplyRead(BaseModel):
    pending_id: int
    workflow_id: int
    run_id: int
    source_message_id: str
    source_account: str
    source_mailbox: str
    source_from: str
    source_subject: str
    to_address: str
    subject: str
    body_draft: str
    status: str
    user_action: str | None
    final_body: str | None
    created_at: datetime
    resolved_at: datetime | None

    class Config:
        from_attributes = True


class PendingEmailReplyActionRequest(BaseModel):
    """Payload for approve / edit-and-send / save-draft / reject actions.
    `final_body` optional — use when the user edited the reply before acting.
    """
    final_body: str | None = None


# ── Dashboard schemas ────────────────────────────────────────


class DashboardStats(BaseModel):
    total_workflows: int = 0
    total_runs: int = 0
    runs_today: int = 0
    scheduler_running: bool = False

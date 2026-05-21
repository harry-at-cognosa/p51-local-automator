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
    config_schema: list | None = None
    enabled: bool
    schedulable: bool

    class Config:
        from_attributes = True


class WorkflowCategoryUpdate(BaseModel):
    """Editable fields on workflow_categories. ID and category_key are immutable."""
    short_name: str | None = None
    long_name: str | None = None
    sort_order: int | None = None
    enabled: bool | None = None


class WorkflowTypeUpdate(BaseModel):
    """Editable fields on workflow_types. ID, type_name, and category are immutable."""
    short_name: str | None = None
    long_name: str | None = None
    type_desc: str | None = None
    default_config: dict | None = None
    required_services: list | dict | None = None
    enabled: bool | None = None


_LLM_STAGES: tuple[str, ...] = ("analyze", "synthesize", "audit", "scribe")


def _validate_stages_override(config: dict | None) -> None:
    """Reject a malformed config.stages list at save time so the failure
    surfaces immediately rather than at workflow-run time.

    Rules for R1 of the pipeline-configurability refactor:
      - stages, when present, must be a non-empty list of strings.
      - every entry must be a known stage name (one of DEFAULT_STAGES).
      - no duplicates. Stage repetition is deferred to R3 (StageSpec).

    Imported lazily so this schema module stays cheap to import.
    """
    if not config:
        return
    raw = config.get("stages")
    if raw is None:
        return
    from backend.services.agentic_engine import DEFAULT_STAGES
    valid = set(DEFAULT_STAGES)
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "config.stages must be a non-empty list of stage names, "
            f"got {raw!r}"
        )
    seen: set[str] = set()
    for s in raw:
        if not isinstance(s, str):
            raise ValueError(
                f"config.stages entries must be strings, got {s!r}"
            )
        if s not in valid:
            raise ValueError(
                f"config.stages contains unknown stage {s!r}. "
                f"Allowed: {sorted(valid)}"
            )
        if s in seen:
            raise ValueError(
                f"config.stages contains duplicate stage {s!r}. "
                "Stage repetition is not yet supported (deferred to R3)."
            )
        seen.add(s)


def _validate_stage_overrides(config: dict | None) -> None:
    """Reject malformed / contradictory config.stage_overrides at save
    time so problems surface in the form, not silently in the runner.

    Rules (R2 cross-field validation):
      - stage_overrides, when present, must be a list of objects (the
        shape produced by the repeating_rows form widget).
      - each entry must have a `stage` value that is one of the four
        LLM-bearing stages (analyze, synthesize, audit, scribe). The
        non-LLM stages (ingest, profile) have no prompt to extend.
      - no duplicate stage entries. If a user wants more guidance on
        one stage, they should consolidate into a single row rather than
        rely on undocumented join semantics.
      - no orphaned addenda: if config.stages is explicitly set, every
        stage referenced in stage_overrides must be in that list. (When
        stages is absent, the workflow runs the full six, so no orphan
        is possible.) Rows whose addendum is blank are tolerated as
        UI scratchpad and don't trigger the orphan check.

    Imported lazily for the same reason as the sibling validator.
    """
    if not config:
        return
    raw = config.get("stage_overrides")
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValueError(
            "config.stage_overrides must be a list of {stage, addendum} "
            f"objects, got {type(raw).__name__}"
        )
    stages_field = config.get("stages")
    effective_stages: set[str] | None = None
    if isinstance(stages_field, list) and stages_field:
        effective_stages = {s for s in stages_field if isinstance(s, str)}
    seen: dict[str, int] = {}
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"config.stage_overrides row {i} must be an object, "
                f"got {type(row).__name__}"
            )
        stage = row.get("stage")
        addendum = (row.get("addendum") or "").strip() if isinstance(row.get("addendum"), str) else ""
        # Skip blank rows (UI may emit empty starter rows).
        if not stage and not addendum:
            continue
        if not isinstance(stage, str) or not stage:
            raise ValueError(
                f"config.stage_overrides row {i} is missing a stage name"
            )
        if stage not in _LLM_STAGES:
            raise ValueError(
                f"config.stage_overrides row {i} targets stage {stage!r}, "
                "which is not an LLM-bearing stage. Addenda are only "
                f"supported for: {list(_LLM_STAGES)}"
            )
        if stage in seen:
            raise ValueError(
                f"config.stage_overrides has duplicate entries for stage "
                f"{stage!r} (rows {seen[stage]} and {i}). Consolidate the "
                "guidance into a single row."
            )
        seen[stage] = i
        if addendum and effective_stages is not None and stage not in effective_stages:
            raise ValueError(
                f"config.stage_overrides row {i} adds guidance for stage "
                f"{stage!r}, but that stage is not in config.stages. "
                "Either re-enable the stage or remove the override row."
            )


def _validate_workflow_config(config: dict | None) -> None:
    """Run all save-time cross-field checks on workflow.config."""
    _validate_stages_override(config)
    _validate_stage_overrides(config)


class UserWorkflowCreate(BaseModel):
    type_id: int
    name: str
    config: dict = {}
    schedule: dict | None = None
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def _validate_schedule_shape(cls, v):
        if v is None:
            return v
        from backend.services.schedule import validate_for_save, ScheduleError
        try:
            validate_for_save(v)
        except ScheduleError as e:
            raise ValueError(str(e))
        return v

    @field_validator("config")
    @classmethod
    def _validate_config_stages(cls, v):
        _validate_workflow_config(v)
        return v


class UserWorkflowRead(BaseModel):
    workflow_id: int
    user_id: int
    group_id: int
    type_id: int
    name: str
    config: dict
    schedule: dict | None
    enabled: bool
    is_adhoc: bool = False
    last_run_at: datetime | None
    created_at: datetime
    type: WorkflowTypeRead | None = None

    class Config:
        from_attributes = True


class UserWorkflowListRead(BaseModel):
    """List-page row: adds nested type (with category) and latest-run status."""
    workflow_id: int
    user_id: int
    group_id: int
    type_id: int
    name: str
    config: dict
    schedule: dict | None
    enabled: bool
    is_adhoc: bool = False
    last_run_at: datetime | None
    created_at: datetime
    type: WorkflowTypeRead
    latest_run_status: str | None
    latest_run_at: datetime | None
    latest_run_artifact_count: int | None
    latest_completed_run_at: datetime | None

    class Config:
        from_attributes = True


class UserWorkflowUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    schedule: dict | None = None
    enabled: bool | None = None

    @field_validator("schedule")
    @classmethod
    def _validate_schedule_shape(cls, v):
        if v is None:
            return v
        from backend.services.schedule import validate_for_save, ScheduleError
        try:
            validate_for_save(v)
        except ScheduleError as e:
            raise ValueError(str(e))
        return v

    @field_validator("config")
    @classmethod
    def _validate_config_stages(cls, v):
        if v is None:
            return v
        _validate_workflow_config(v)
        return v


class BulkDeleteRequest(BaseModel):
    workflow_ids: list[int]


class WorkflowRunRead(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str = ""
    status: str
    current_step: int
    total_steps: int
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    error_detail: str | None
    artifact_count: int = 0
    config_snapshot: dict | None = None
    archived: bool = False
    type_id: int | None = None         # populated by detail endpoint only
    config_schema: list | None = None  # populated by detail endpoint only

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
    # Agentic-engine annotations; NULL for steps from types 1–6.
    stage: str | None = None
    kind: str | None = None

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


# ── Gmail schemas (Track B Phase B1) ─────────────────────────


class GmailAccountRead(BaseModel):
    """Public view of a connected Gmail account.

    Deliberately omits the encrypted token columns. `scopes` is stored as
    a space-separated string (Google OAuth convention); the frontend can
    split for display.
    """
    id: int
    email: str
    status: str
    scopes: str
    created_at: datetime
    last_used_at: datetime | None
    access_token_expires_at: datetime | None

    class Config:
        from_attributes = True


# ── Dashboard schemas ────────────────────────────────────────


class DashboardStats(BaseModel):
    total_workflows: int = 0
    total_runs: int = 0
    runs_today: int = 0
    scheduler_running: bool = False

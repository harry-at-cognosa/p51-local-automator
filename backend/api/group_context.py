"""Request-scoped group context for superusers.

A superuser may act as a member of any one group, or view across all of
them. Everyone else is permanently confined to their own group and the
header below is ignored for them.

Two modes:

  CONCRETE GROUP — the superuser *is* a member of that group for the
    duration of the request. Lists, detail pages, writes, the file picker
    and the filesystem root all resolve to it. There is deliberately no
    state in which the group you can write to differs from the group you
    are acting as, so a superuser can never create or modify data in a
    group other than the one currently selected.

  ALL GROUPS — the default, and today's historical superuser behaviour.
    List endpoints return every group's rows so the whole system is
    visible at a glance. Anything that opens, runs or modifies a single
    row requires a concrete group first (see require_concrete_group):
    all-groups is a viewing mode, not an operating one.

The context is carried per request in the X-Group-Context header rather
than stored on the user row or in server-side session state. Two reasons:

  1. Server-side "assumed group" is a hidden mode that leaks across tabs —
     the same session would be group 1 in one tab and group 2 in another,
     with no way to tell which produced a given result.
  2. The authenticated User object shares the request's DB session (see
     async_get_user_db), and backend/api/users.py flushes and commits it
     on the profile route. Overriding User.group_id in memory would
     therefore be written to the user row permanently the next time that
     route ran. The context must never touch ORM state, so it is kept
     beside the user rather than on it.

Mirrors the convention already established by _resolve_group_id in
backend/api/group_settings.py: the caller names the group, the server
honours it only for superusers.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from backend.auth.users import current_active_user
from backend.db.models import User, UserWorkflows


GROUP_CONTEXT_HEADER = "X-Group-Context"
ALL_GROUPS = "all"


@dataclass(frozen=True)
class GroupContext:
    """Which group the caller is acting as for this request.

    `group_id` is None only in all-groups mode, which only a superuser can
    reach. Read it through require_concrete_group anywhere a single group
    is needed, so the None case fails loudly instead of silently becoming
    a NULL comparison.
    """
    user: User
    group_id: int | None

    @property
    def is_all_groups(self) -> bool:
        return self.group_id is None


def resolve_group_context(user: User, raw: str | None) -> GroupContext:
    """Build the context from a raw header or query-param value.

    Separate from the dependency because artifact downloads authenticate
    from a query-param token rather than a header — a browser following a
    download link cannot set either one — so that route has to resolve the
    context by hand from its own query param.

    Non-superusers always get their own group; the value is ignored rather
    than rejected, so a stale context left in a client's store cannot lock
    a regular user out of their own data.
    """
    if not user.is_superuser:
        return GroupContext(user=user, group_id=user.group_id)

    if raw is None or raw.strip().lower() == ALL_GROUPS:
        return GroupContext(user=user, group_id=None)

    try:
        return GroupContext(user=user, group_id=int(raw))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"{GROUP_CONTEXT_HEADER} must be a group id or '{ALL_GROUPS}'",
        )


async def get_group_context(
    user: User = Depends(current_active_user),
    x_group_context: str | None = Header(default=None),
) -> GroupContext:
    """The acting group for this request, from the X-Group-Context header."""
    return resolve_group_context(user, x_group_context)


def scope_filter(ctx: GroupContext) -> list:
    """WHERE-clauses scoping a query that joins UserWorkflows to the rows
    the caller may see. Replaces the older _run_scope_filter(user).

    - superuser, all groups  → no filter (every group)
    - superuser, concrete    → that group only, exactly as a member sees it
    - groupadmin / manager   → their own group
    - everyone else          → only workflows they own
    """
    user = ctx.user
    if user.is_superuser:
        if ctx.is_all_groups:
            return []
        return [UserWorkflows.group_id == ctx.group_id]
    if user.is_groupadmin or user.is_manager:
        return [UserWorkflows.group_id == user.group_id]
    return [UserWorkflows.user_id == user.user_id]


def require_concrete_group(ctx: GroupContext) -> int:
    """The group to act as, or 409 if the caller is in all-groups mode.

    All-groups shows rows from every group at once, so there is no single
    group a write could belong to and no unambiguous group a detail page
    could be read in. Rather than guess, make the caller choose — the UI
    hides these affordances in all-groups mode, so a 409 here means a
    client got out of step, not that a user did something wrong.
    """
    if ctx.is_all_groups:
        raise HTTPException(
            status_code=409,
            detail="Select a group before working with an individual workflow. "
                   "All-groups is a view-only mode.",
        )
    return ctx.group_id


def group_or_home(ctx: GroupContext) -> int:
    """The acting group, falling back to the caller's own group.

    For read-only endpoints that always need *some* group and have a
    sensible answer in all-groups mode — the system health banner, which
    the Dashboard loads unconditionally and which should report on the
    superuser's own group rather than refuse. Never use this where a write
    could follow; use require_concrete_group so the caller must choose.
    """
    return ctx.user.group_id if ctx.is_all_groups else ctx.group_id

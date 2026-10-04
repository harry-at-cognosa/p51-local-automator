"""Unit tests for the superuser group context.

Hermetic — no DB, no HTTP. The functions under test read plain attributes
off the user, so a stub stands in for the ORM object.

The guarantee these tests exist to protect: a superuser can never create or
modify data in a group other than the one they are currently acting as.
That holds because every write derives its group from the same context the
reads do, and because all-groups mode — the one state with no single group —
refuses to produce a group id at all.

Run with: pytest backend/tests/test_group_context.py -v
"""
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from backend.api.group_context import (
    ALL_GROUPS,
    GroupContext,
    group_or_home,
    require_concrete_group,
    resolve_group_context,
    scope_filter,
)


@dataclass
class StubUser:
    user_id: int = 1
    group_id: int = 1
    is_superuser: bool = False
    is_groupadmin: bool = False
    is_manager: bool = False


SUPER = StubUser(user_id=1, group_id=1, is_superuser=True, is_groupadmin=True, is_manager=True)
GROUPADMIN = StubUser(user_id=2, group_id=2, is_groupadmin=True)
MANAGER = StubUser(user_id=3, group_id=2, is_manager=True)
EMPLOYEE = StubUser(user_id=4, group_id=2)


def clauses(ctx) -> list[str]:
    return [str(c) for c in scope_filter(ctx)]


# ── resolving the context ───────────────────────────────────


@pytest.mark.parametrize("raw", [None, ALL_GROUPS, "ALL", " all "])
def test_superuser_defaults_to_all_groups(raw):
    ctx = resolve_group_context(SUPER, raw)
    assert ctx.is_all_groups is True
    assert ctx.group_id is None


def test_superuser_can_act_as_a_concrete_group():
    ctx = resolve_group_context(SUPER, "2")
    assert ctx.group_id == 2
    assert ctx.is_all_groups is False


def test_superuser_rejects_a_malformed_context():
    with pytest.raises(HTTPException) as e:
        resolve_group_context(SUPER, "group-two")
    assert e.value.status_code == 400


@pytest.mark.parametrize("user", [GROUPADMIN, MANAGER, EMPLOYEE])
@pytest.mark.parametrize("raw", [None, ALL_GROUPS, "1", "99", "nonsense"])
def test_non_superusers_are_pinned_to_their_own_group(user, raw):
    """The header is ignored, never rejected — a stale value left in a
    client store must not be able to lock a regular user out, nor let them
    peek at another group."""
    ctx = resolve_group_context(user, raw)
    assert ctx.group_id == user.group_id
    assert ctx.is_all_groups is False


# ── what each role sees ─────────────────────────────────────


def test_superuser_all_groups_is_unfiltered():
    assert clauses(resolve_group_context(SUPER, None)) == []


def test_superuser_in_a_group_is_filtered_to_it():
    got = clauses(resolve_group_context(SUPER, "2"))
    assert len(got) == 1 and "group_id" in got[0]


def test_superuser_in_a_group_sees_what_a_member_sees():
    """The whole point of switching: identical scoping to a groupadmin of
    that group, not a privileged superset."""
    as_super = clauses(resolve_group_context(SUPER, "2"))
    as_member = clauses(resolve_group_context(GROUPADMIN, None))
    assert as_super == as_member


@pytest.mark.parametrize("user", [GROUPADMIN, MANAGER])
def test_group_roles_are_scoped_to_their_group(user):
    got = clauses(resolve_group_context(user, None))
    assert len(got) == 1 and "group_id" in got[0]


def test_employee_is_scoped_to_their_own_rows():
    got = clauses(resolve_group_context(EMPLOYEE, None))
    assert len(got) == 1 and "user_id" in got[0]


# ── the no-cross-group-write guarantee ──────────────────────


def test_all_groups_mode_refuses_to_name_a_group():
    """Writes and detail reads all route through require_concrete_group, so
    refusing here is what makes all-groups view-only."""
    with pytest.raises(HTTPException) as e:
        require_concrete_group(resolve_group_context(SUPER, None))
    assert e.value.status_code == 409


def test_concrete_mode_names_exactly_the_acting_group():
    assert require_concrete_group(resolve_group_context(SUPER, "2")) == 2


def test_non_superuser_always_writes_to_their_own_group():
    """Even with another group requested, the group a write lands in is
    their own — the request cannot redirect it."""
    assert require_concrete_group(resolve_group_context(EMPLOYEE, "1")) == EMPLOYEE.group_id


def test_the_group_read_and_the_group_written_are_the_same():
    """There is deliberately no state where these differ; that identity is
    what makes the cross-group write impossible rather than merely guarded."""
    for raw in ("1", "2", "7"):
        ctx = resolve_group_context(SUPER, raw)
        read_scope = scope_filter(ctx)
        assert len(read_scope) == 1
        assert str(require_concrete_group(ctx)) in str(read_scope[0].right.value)


# ── the read-only fallback ──────────────────────────────────


def test_group_or_home_falls_back_in_all_groups_mode():
    assert group_or_home(resolve_group_context(SUPER, None)) == SUPER.group_id


def test_group_or_home_follows_a_concrete_group():
    assert group_or_home(resolve_group_context(SUPER, "2")) == 2


def test_group_context_is_immutable():
    """It must not be possible to retarget the context mid-request after
    the scope has already been computed from it."""
    ctx = GroupContext(user=SUPER, group_id=1)
    with pytest.raises(Exception):
        ctx.group_id = 2

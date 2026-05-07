"""Unit tests for the skill registry primitives.

Hermetic — no DB, no HTTP, no filesystem. Verifies the @register
decorator wires a callable into SKILL_REGISTRY, that to_anthropic_tools
serializes the metadata correctly, and that duplicate names raise.

Run with: pytest backend/tests/test_skills_registry.py -v
"""
import pytest

from backend.services.skills.registry import (
    SKILL_REGISTRY,
    Skill,
    SkillContext,
    register,
    to_anthropic_tools,
)


@pytest.fixture(autouse=True)
def isolate_registry():
    """Snapshot and restore SKILL_REGISTRY around each test so registrations
    in one test don't leak into the next."""
    snapshot = dict(SKILL_REGISTRY)
    yield
    SKILL_REGISTRY.clear()
    SKILL_REGISTRY.update(snapshot)


def test_skill_context_defaults():
    ctx = SkillContext(run_id=42, artifacts_dir="/tmp/run42")
    assert ctx.run_id == 42
    assert ctx.tables == {}
    assert ctx.llm_client is None
    assert ctx.log_step is None


def test_register_adds_to_registry_and_returns_function():
    @register(
        name="_test_noop",
        description="No-op for tests",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
    )
    async def noop(ctx):
        return {"ok": True}

    assert "_test_noop" in SKILL_REGISTRY
    skill = SKILL_REGISTRY["_test_noop"]
    assert isinstance(skill, Skill)
    assert skill.name == "_test_noop"
    assert skill.on_failure == "abort"  # default
    # Decorator returns the underlying callable unchanged
    assert callable(noop)


def test_register_rejects_duplicate_name():
    @register(
        name="_test_dup",
        description="first",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    async def first(ctx):
        return None

    with pytest.raises(ValueError, match="Duplicate skill"):

        @register(
            name="_test_dup",
            description="second",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        async def second(ctx):
            return None


def test_register_respects_on_failure_override():
    @register(
        name="_test_skip",
        description="skip-on-fail skill",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        on_failure="skip",
    )
    async def skip_skill(ctx):
        return None

    assert SKILL_REGISTRY["_test_skip"].on_failure == "skip"


def test_to_anthropic_tools_serializes_subset():
    @register(
        name="_test_a",
        description="alpha",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        output_schema={"type": "object"},
    )
    async def a(ctx, x):
        return None

    @register(
        name="_test_b",
        description="beta",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    async def b(ctx):
        return None

    tools = to_anthropic_tools(names=["_test_a"])
    assert len(tools) == 1
    assert tools[0]["name"] == "_test_a"
    assert tools[0]["description"] == "alpha"
    assert tools[0]["input_schema"]["properties"]["x"]["type"] == "string"
    # output_schema is not exposed to the LLM
    assert "output_schema" not in tools[0]

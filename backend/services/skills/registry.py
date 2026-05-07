"""Skill protocol, runtime context, and registry for AWF-1.

A skill is a deterministic or LLM-callable unit of work the engine can
invoke. Each skill declares:

- name (registry key, also the Anthropic tool-use tool name)
- description (one-line, used both internally and as the LLM tool description)
- input_schema (JSON Schema; doubles as the Anthropic tool input_schema)
- output_schema (JSON Schema; used by unit tests + audit-stage validation)
- on_failure ("skip" | "abort" | "retry_once") — author-declared default,
  the engine may override per-call
- run (async callable: `async def run(ctx, **kwargs) -> Any`)

Registration is via `@register(...)` in each skill module. The skill
module's import side-effect populates SKILL_REGISTRY. The package
__init__ imports each skill module so a single
`import backend.services.skills` brings the full catalog online.

This module deliberately has no third-party imports beyond stdlib +
typing — every skill module that depends on pandas/matplotlib/etc. owns
those imports. Keeps the registry lightweight and easy to import in
non-runtime contexts (tests, schema generation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal


OnFailure = Literal["skip", "abort", "retry_once"]


@dataclass
class SkillContext:
    """Runtime context handed to every skill invocation.

    The engine constructs one SkillContext per workflow run. Skills
    mutate `tables` in place — `data_io.load_csv` populates it,
    downstream skills read from it. `artifacts_dir` is the per-run
    output directory; skills that emit files (charts, reports) write
    here and record an artifact via the engine.

    `llm_client` is None for stages that don't call the LLM (ingest,
    profile). `log_step` is None in unit-test contexts; the engine
    wires it to a callback that writes a workflow_steps row.
    """

    run_id: int
    artifacts_dir: str
    tables: dict[str, Any] = field(default_factory=dict)  # name -> pandas.DataFrame
    llm_client: Any = None
    log_step: Callable[..., Awaitable[None]] | None = None


@dataclass
class Skill:
    """Registered skill metadata + callable."""

    name: str
    description: str
    input_schema: dict
    output_schema: dict
    on_failure: OnFailure
    run: Callable[..., Awaitable[Any]]


SKILL_REGISTRY: dict[str, Skill] = {}


def register(
    *,
    name: str,
    description: str,
    input_schema: dict,
    output_schema: dict,
    on_failure: OnFailure = "abort",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator: wrap an async function as a Skill and register it.

    The decorated function is returned unchanged so unit tests can call
    it directly without going through the registry.
    """

    def wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if name in SKILL_REGISTRY:
            raise ValueError(f"Duplicate skill registration: {name!r}")
        SKILL_REGISTRY[name] = Skill(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            on_failure=on_failure,
            run=fn,
        )
        return fn

    return wrap


def to_anthropic_tools(names: list[str] | None = None) -> list[dict]:
    """Serialize skills to Anthropic SDK tool definitions.

    Pass `names` to expose only a curated subset to the LLM (e.g. the
    analyze stage gets descriptive_stats + charts, but not data_io).
    """
    if names is None:
        skills = list(SKILL_REGISTRY.values())
    else:
        skills = [SKILL_REGISTRY[n] for n in names]
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.input_schema,
        }
        for s in skills
    ]


def get_skill(name: str) -> Skill:
    """Lookup a registered skill by name. Raises KeyError if unknown."""
    return SKILL_REGISTRY[name]

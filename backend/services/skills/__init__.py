"""AWF-1 skill catalog.

Importing this package triggers registration of every skill module so
`SKILL_REGISTRY` is populated. Most callers only need the registry and
context types — re-exported here for convenience.
"""
from backend.services.skills.registry import (
    OnFailure,
    Skill,
    SkillContext,
    SKILL_REGISTRY,
    get_skill,
    register,
    to_anthropic_tools,
)

# Side-effect imports: each module's @register decorators run on import,
# populating SKILL_REGISTRY. Order doesn't matter; names are unique.
from backend.services.skills import data_io  # noqa: F401
from backend.services.skills import descriptive_stats  # noqa: F401
from backend.services.skills import charts  # noqa: F401


__all__ = [
    "OnFailure",
    "Skill",
    "SkillContext",
    "SKILL_REGISTRY",
    "get_skill",
    "register",
    "to_anthropic_tools",
]

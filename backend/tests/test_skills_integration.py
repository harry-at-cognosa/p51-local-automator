"""Integration test for the AWF-1 skill catalog.

Verifies that a single `import backend.services.skills` populates
SKILL_REGISTRY with the full A2 catalog and that the registry's
Anthropic-tool serialization is shape-correct.

Run with: pytest backend/tests/test_skills_integration.py -v
"""
import backend.services.skills as skills


EXPECTED_SKILLS = {
    # data_io (A2.2)
    "load_csv", "load_xlsx", "write_artifact",
    # descriptive_stats (A2.3)
    "describe_column", "value_distribution", "correlation_matrix", "groupby_aggregate",
    # charts (A2.4)
    "create_scatter_plot", "create_histogram", "create_bar_chart", "create_correlation_heatmap",
}


def test_full_catalog_registers_on_package_import():
    """Single import of the package brings every A2 skill online."""
    assert EXPECTED_SKILLS.issubset(skills.SKILL_REGISTRY.keys()), (
        f"Missing: {EXPECTED_SKILLS - set(skills.SKILL_REGISTRY)}"
    )


def test_no_unexpected_skills_leak_in():
    """If a future commit adds a new skill, this test fails loudly so the
    catalog stays auditable. Update EXPECTED_SKILLS when adding skills."""
    extra = set(skills.SKILL_REGISTRY) - EXPECTED_SKILLS
    # Allow underscore-prefixed test fixtures (registered + cleaned in unit tests)
    leaked = {n for n in extra if not n.startswith("_test_")}
    assert not leaked, f"Unexpected skills in registry: {leaked}"


def test_to_anthropic_tools_full_catalog():
    """to_anthropic_tools() returns one entry per registered skill in
    the SDK-required shape (name, description, input_schema)."""
    tools = skills.to_anthropic_tools()
    names = {t["name"] for t in tools}
    assert EXPECTED_SKILLS.issubset(names)

    for t in tools:
        assert set(t.keys()) == {"name", "description", "input_schema"}, (
            f"Tool {t['name']!r} has unexpected keys {set(t.keys())}"
        )
        assert isinstance(t["description"], str) and t["description"]
        assert t["input_schema"]["type"] == "object"
        assert "properties" in t["input_schema"]


def test_to_anthropic_tools_subsetting():
    """Curated subsets work — analyze stage will use this to expose only
    the read-only skills, not load_csv / write_artifact."""
    analyze_set = [
        "describe_column", "value_distribution", "correlation_matrix",
        "groupby_aggregate", "create_scatter_plot", "create_histogram",
        "create_bar_chart", "create_correlation_heatmap",
    ]
    tools = skills.to_anthropic_tools(names=analyze_set)
    assert {t["name"] for t in tools} == set(analyze_set)


def test_on_failure_policy_per_skill():
    """Sanity-check the curated on_failure assignments. Loaders abort
    (no data => no run), descriptive stats split, charts skip."""
    abort = {"load_csv", "load_xlsx", "write_artifact",
             "describe_column", "value_distribution", "groupby_aggregate"}
    skip = {"correlation_matrix",
            "create_scatter_plot", "create_histogram",
            "create_bar_chart", "create_correlation_heatmap"}
    for name in abort:
        assert skills.SKILL_REGISTRY[name].on_failure == "abort", name
    for name in skip:
        assert skills.SKILL_REGISTRY[name].on_failure == "skip", name


def test_get_skill_lookup():
    s = skills.get_skill("load_csv")
    assert s.name == "load_csv"
    assert callable(s.run)

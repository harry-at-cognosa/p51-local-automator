"""Hermetic unit tests for descriptive_stats skills.

Each test builds a synthetic DataFrame, drops it into ctx.tables, runs
the skill, and asserts shape + values. No file I/O; tmp_path is unused.

Run with: pytest backend/tests/test_skills_descriptive_stats.py -v
"""
import math

import pandas as pd
import pytest

from backend.services.skills.descriptive_stats import (
    correlation_matrix,
    describe_column,
    groupby_aggregate,
    value_distribution,
)
from backend.services.skills.registry import SKILL_REGISTRY, SkillContext


def _ctx_with(table_name: str, df: pd.DataFrame) -> SkillContext:
    ctx = SkillContext(run_id=1, artifacts_dir="/tmp/unused")
    ctx.tables[table_name] = df
    return ctx


# ── describe_column ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_column_numeric():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
    ctx = _ctx_with("t", df)

    result = await describe_column(ctx, table_name="t", column="x")

    assert result["dtype"].startswith("int")
    assert result["stats"]["count"] == 5
    assert result["stats"]["min"] == 1
    assert result["stats"]["max"] == 5
    assert result["stats"]["mean"] == 3.0
    assert result["stats"]["null_count"] == 0


@pytest.mark.asyncio
async def test_describe_column_categorical_and_nulls():
    df = pd.DataFrame({"cat": ["a", "b", "a", None, "a"]})
    ctx = _ctx_with("t", df)

    result = await describe_column(ctx, table_name="t", column="cat")

    assert result["stats"]["count"] == 4
    assert result["stats"]["top"] == "a"
    assert result["stats"]["null_count"] == 1


@pytest.mark.asyncio
async def test_describe_column_handles_nan_inf_to_none():
    df = pd.DataFrame({"x": [float("nan"), 1.0, 2.0]})
    ctx = _ctx_with("t", df)

    result = await describe_column(ctx, table_name="t", column="x")

    # describe() drops NaN — count==2; std defined for n>=2
    assert result["stats"]["count"] == 2
    # No NaN/Inf should leak through to JSON-bound output
    for v in result["stats"].values():
        assert v is None or not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


@pytest.mark.asyncio
async def test_describe_column_unknown_table():
    ctx = SkillContext(run_id=1, artifacts_dir="/tmp")
    with pytest.raises(KeyError, match="not loaded"):
        await describe_column(ctx, table_name="ghost", column="x")


@pytest.mark.asyncio
async def test_describe_column_unknown_column():
    df = pd.DataFrame({"x": [1, 2]})
    ctx = _ctx_with("t", df)
    with pytest.raises(KeyError, match="not found"):
        await describe_column(ctx, table_name="t", column="missing")


# ── value_distribution ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_value_distribution_top_and_pct():
    df = pd.DataFrame({"c": ["a", "a", "a", "b", "b", "c"]})
    ctx = _ctx_with("t", df)

    result = await value_distribution(ctx, table_name="t", column="c", top_n=3)

    assert result["total"] == 6
    assert result["distinct"] == 3
    top = result["top"]
    assert top[0]["value"] == "a"
    assert top[0]["count"] == 3
    assert top[0]["pct"] == 50.0
    assert top[1]["value"] == "b"
    assert top[1]["count"] == 2
    assert round(top[1]["pct"], 2) == 33.33


@pytest.mark.asyncio
async def test_value_distribution_top_n_truncates():
    df = pd.DataFrame({"c": list("abcdefghij")})  # 10 distinct values
    ctx = _ctx_with("t", df)

    result = await value_distribution(ctx, table_name="t", column="c", top_n=3)

    assert len(result["top"]) == 3
    assert result["distinct"] == 10


# ── correlation_matrix ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correlation_matrix_perfect_correlation():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [10, 20, 30, 40], "label": ["a"] * 4})
    ctx = _ctx_with("t", df)

    result = await correlation_matrix(ctx, table_name="t")

    # Non-numeric "label" auto-skipped
    assert set(result["columns"]) == {"x", "y"}
    assert result["method"] == "pearson"
    assert result["matrix"]["x"]["y"] == pytest.approx(1.0)
    assert result["matrix"]["x"]["x"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_correlation_matrix_explicit_columns_must_be_numeric():
    df = pd.DataFrame({"x": [1, 2, 3], "label": ["a", "b", "c"]})
    ctx = _ctx_with("t", df)

    with pytest.raises(KeyError, match="Non-numeric or missing"):
        await correlation_matrix(ctx, table_name="t", columns=["x", "label"])


@pytest.mark.asyncio
async def test_correlation_matrix_method_validation():
    df = pd.DataFrame({"x": [1, 2, 3]})
    ctx = _ctx_with("t", df)

    with pytest.raises(ValueError, match="method must be"):
        await correlation_matrix(ctx, table_name="t", method="bogus")


# ── groupby_aggregate ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_groupby_aggregate_sum():
    df = pd.DataFrame(
        {
            "region": ["N", "N", "S", "S", "S"],
            "amount": [10, 20, 30, 40, 50],
        }
    )
    ctx = _ctx_with("t", df)

    result = await groupby_aggregate(
        ctx, table_name="t", group_by="region", agg_column="amount", agg_func="sum"
    )

    by_key = {g["key"]: g["value"] for g in result["groups"]}
    assert by_key["N"] == 30
    assert by_key["S"] == 120
    assert result["agg_func"] == "sum"


@pytest.mark.asyncio
async def test_groupby_aggregate_invalid_func():
    df = pd.DataFrame({"a": [1], "b": [1]})
    ctx = _ctx_with("t", df)
    with pytest.raises(ValueError, match="agg_func must be"):
        await groupby_aggregate(
            ctx, table_name="t", group_by="a", agg_column="b", agg_func="bogus"
        )


# ── registry wiring ──────────────────────────────────────────────────


def test_descriptive_stats_skills_are_registered():
    for n in ("describe_column", "value_distribution", "correlation_matrix", "groupby_aggregate"):
        assert n in SKILL_REGISTRY, f"{n} not registered"
    assert SKILL_REGISTRY["correlation_matrix"].on_failure == "skip"

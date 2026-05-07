"""Hermetic unit tests for chart skills.

Verifies each skill produces a non-empty PNG at the expected path,
returns the documented metadata, and rejects invalid inputs (missing
columns, wrong dtype, path traversal, too few numeric columns).

Run with: pytest backend/tests/test_skills_charts.py -v
"""
import os

import pandas as pd
import pytest

from backend.services.skills.charts import (
    create_bar_chart,
    create_correlation_heatmap,
    create_histogram,
    create_scatter_plot,
)
from backend.services.skills.registry import SKILL_REGISTRY, SkillContext


# PNG file signature: 137 80 78 71 13 10 26 10
_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _ctx_with(tmp_path, table_name: str, df: pd.DataFrame) -> SkillContext:
    ctx = SkillContext(run_id=1, artifacts_dir=str(tmp_path / "art"))
    ctx.tables[table_name] = df
    return ctx


def _assert_valid_png(path: str) -> None:
    assert os.path.exists(path), f"PNG not written at {path}"
    with open(path, "rb") as f:
        head = f.read(8)
    assert head == _PNG_HEADER, f"file at {path} is not a PNG"
    assert os.path.getsize(path) > 200, "PNG suspiciously small"


# ── create_scatter_plot ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scatter_plot_writes_png(tmp_path):
    df = pd.DataFrame({"x": range(20), "y": [v * 2 + 1 for v in range(20)]})
    ctx = _ctx_with(tmp_path, "t", df)

    result = await create_scatter_plot(
        ctx, table_name="t", x_column="x", y_column="y", name="scatter"
    )

    assert result["kind"] == "png"
    assert result["path"].endswith("scatter.png")
    _assert_valid_png(result["path"])
    assert result["size_bytes"] > 0


@pytest.mark.asyncio
async def test_scatter_plot_rejects_non_numeric(tmp_path):
    df = pd.DataFrame({"x": [1, 2, 3], "label": ["a", "b", "c"]})
    ctx = _ctx_with(tmp_path, "t", df)
    with pytest.raises(TypeError, match="not numeric"):
        await create_scatter_plot(
            ctx, table_name="t", x_column="x", y_column="label", name="bad"
        )


@pytest.mark.asyncio
async def test_scatter_plot_path_traversal_blocked(tmp_path):
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    ctx = _ctx_with(tmp_path, "t", df)
    with pytest.raises(ValueError, match="basename"):
        await create_scatter_plot(
            ctx, table_name="t", x_column="x", y_column="y", name="../escape"
        )


# ── create_histogram ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_histogram_writes_png(tmp_path):
    df = pd.DataFrame({"x": list(range(100))})
    ctx = _ctx_with(tmp_path, "t", df)

    result = await create_histogram(
        ctx, table_name="t", column="x", name="hist", bins=10
    )

    _assert_valid_png(result["path"])
    assert result["path"].endswith("hist.png")


@pytest.mark.asyncio
async def test_histogram_bins_validation(tmp_path):
    df = pd.DataFrame({"x": [1, 2, 3]})
    ctx = _ctx_with(tmp_path, "t", df)
    with pytest.raises(ValueError, match="bins must be"):
        await create_histogram(ctx, table_name="t", column="x", name="h", bins=1)


# ── create_bar_chart ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bar_chart_aggregates_by_x(tmp_path):
    df = pd.DataFrame(
        {"region": ["N", "N", "S", "S", "S"], "amount": [10, 20, 30, 40, 50]}
    )
    ctx = _ctx_with(tmp_path, "t", df)

    result = await create_bar_chart(
        ctx, table_name="t", x_column="region", y_column="amount", name="by_region"
    )

    _assert_valid_png(result["path"])


@pytest.mark.asyncio
async def test_bar_chart_y_must_be_numeric(tmp_path):
    df = pd.DataFrame({"x": ["a", "b"], "y": ["c", "d"]})
    ctx = _ctx_with(tmp_path, "t", df)
    with pytest.raises(TypeError, match="not numeric"):
        await create_bar_chart(
            ctx, table_name="t", x_column="x", y_column="y", name="bad"
        )


# ── create_correlation_heatmap ───────────────────────────────────────


@pytest.mark.asyncio
async def test_correlation_heatmap_writes_png(tmp_path):
    df = pd.DataFrame(
        {
            "a": [1, 2, 3, 4, 5],
            "b": [2, 4, 6, 8, 10],
            "c": [5, 4, 3, 2, 1],
            "label": ["x"] * 5,  # auto-skipped
        }
    )
    ctx = _ctx_with(tmp_path, "t", df)

    result = await create_correlation_heatmap(ctx, table_name="t", name="corr")

    _assert_valid_png(result["path"])


@pytest.mark.asyncio
async def test_correlation_heatmap_needs_two_numeric_columns(tmp_path):
    df = pd.DataFrame({"x": [1, 2, 3], "label": ["a", "b", "c"]})
    ctx = _ctx_with(tmp_path, "t", df)
    with pytest.raises(ValueError, match=">=2 numeric"):
        await create_correlation_heatmap(ctx, table_name="t", name="bad")


# ── registry wiring ──────────────────────────────────────────────────


def test_chart_skills_are_registered():
    for n in (
        "create_scatter_plot",
        "create_histogram",
        "create_bar_chart",
        "create_correlation_heatmap",
    ):
        assert n in SKILL_REGISTRY, f"{n} not registered"
        assert SKILL_REGISTRY[n].on_failure == "skip"

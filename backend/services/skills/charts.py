"""Chart-rendering skills.

Four PNG-emitting skills using matplotlib's headless Agg backend.
Output goes to ctx.artifacts_dir/<name>.png; the skill returns the
path so the engine can record an artifact row.

The Agg backend is set at module-import time, before pyplot is touched.
This module is imported by backend.services.skills.__init__ as part of
the registry warm-up — picking the backend later (after another module
has set Qt/Tk) is unsafe.
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (intentionally after .use())
import pandas as pd  # noqa: E402

from backend.services.skills.registry import SkillContext, register  # noqa: E402


def _require_table(ctx: SkillContext, table_name: str) -> pd.DataFrame:
    if table_name not in ctx.tables:
        raise KeyError(f"Table {table_name!r} is not loaded. Available: {list(ctx.tables)}")
    return ctx.tables[table_name]


def _validate_basename(name: str) -> str:
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise ValueError(f"name must be a basename, got {name!r}")
    if not name.lower().endswith(".png"):
        name = name + ".png"
    return name


def _save(fig, ctx: SkillContext, name: str) -> dict:
    name = _validate_basename(name)
    os.makedirs(ctx.artifacts_dir, exist_ok=True)
    path = os.path.join(ctx.artifacts_dir, name)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return {"path": path, "kind": "png", "size_bytes": os.path.getsize(path)}


def _require_numeric(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        if c not in df.columns:
            raise KeyError(f"Column {c!r} not in table (columns={list(df.columns)})")
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise TypeError(f"Column {c!r} is not numeric (dtype={df[c].dtype})")


@register(
    name="create_scatter_plot",
    description=(
        "Render a scatter plot of two numeric columns and save as PNG. "
        "Returns the file path so the engine can record the artifact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "x_column": {"type": "string"},
            "y_column": {"type": "string"},
            "name": {
                "type": "string",
                "description": "Output filename (basename only; .png extension auto-appended).",
            },
            "title": {"type": ["string", "null"]},
        },
        "required": ["table_name", "x_column", "y_column", "name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string"},
            "size_bytes": {"type": "integer"},
        },
        "required": ["path", "kind", "size_bytes"],
    },
    on_failure="skip",
)
async def create_scatter_plot(
    ctx: SkillContext,
    *,
    table_name: str,
    x_column: str,
    y_column: str,
    name: str,
    title: str | None = None,
) -> dict:
    df = _require_table(ctx, table_name)
    _require_numeric(df, x_column, y_column)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df[x_column], df[y_column], alpha=0.6, s=24)
    ax.set_xlabel(x_column)
    ax.set_ylabel(y_column)
    ax.set_title(title or f"{y_column} vs {x_column}")
    ax.grid(True, alpha=0.3)
    return _save(fig, ctx, name)


@register(
    name="create_histogram",
    description=(
        "Render a histogram of a single numeric column. Default 20 bins. "
        "Saves a PNG and returns its path."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "bins": {"type": "integer", "default": 20, "minimum": 2, "maximum": 200},
            "name": {"type": "string"},
            "title": {"type": ["string", "null"]},
        },
        "required": ["table_name", "column", "name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string"},
            "size_bytes": {"type": "integer"},
        },
        "required": ["path", "kind", "size_bytes"],
    },
    on_failure="skip",
)
async def create_histogram(
    ctx: SkillContext,
    *,
    table_name: str,
    column: str,
    name: str,
    bins: int = 20,
    title: str | None = None,
) -> dict:
    df = _require_table(ctx, table_name)
    _require_numeric(df, column)
    if not 2 <= bins <= 200:
        raise ValueError(f"bins must be in [2, 200]; got {bins}")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(df[column].dropna(), bins=bins, edgecolor="black", alpha=0.75)
    ax.set_xlabel(column)
    ax.set_ylabel("Frequency")
    ax.set_title(title or f"Distribution of {column}")
    ax.grid(True, alpha=0.3)
    return _save(fig, ctx, name)


@register(
    name="create_bar_chart",
    description=(
        "Render a bar chart of a numeric column aggregated by a categorical "
        "column. The aggregation is sum if multiple rows share an x value."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "x_column": {
                "type": "string",
                "description": "Categorical column for the x-axis.",
            },
            "y_column": {
                "type": "string",
                "description": "Numeric column for the bar height (summed within each x bucket).",
            },
            "name": {"type": "string"},
            "title": {"type": ["string", "null"]},
        },
        "required": ["table_name", "x_column", "y_column", "name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string"},
            "size_bytes": {"type": "integer"},
        },
        "required": ["path", "kind", "size_bytes"],
    },
    on_failure="skip",
)
async def create_bar_chart(
    ctx: SkillContext,
    *,
    table_name: str,
    x_column: str,
    y_column: str,
    name: str,
    title: str | None = None,
) -> dict:
    df = _require_table(ctx, table_name)
    if x_column not in df.columns:
        raise KeyError(f"Column {x_column!r} not in table (columns={list(df.columns)})")
    _require_numeric(df, y_column)

    grouped = df.groupby(x_column)[y_column].sum()
    fig, ax = plt.subplots(figsize=(max(8, 0.4 * len(grouped) + 4), 5))
    ax.bar([str(k) for k in grouped.index], grouped.values)
    ax.set_xlabel(x_column)
    ax.set_ylabel(f"sum({y_column})")
    ax.set_title(title or f"{y_column} by {x_column}")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, ctx, name)


@register(
    name="create_correlation_heatmap",
    description=(
        "Render a correlation heatmap over the numeric columns of a table. "
        "Pearson correlation by default. Saves a PNG and returns the path."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "columns": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Optional whitelist of numeric columns.",
            },
            "name": {"type": "string"},
            "title": {"type": ["string", "null"]},
        },
        "required": ["table_name", "name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string"},
            "size_bytes": {"type": "integer"},
        },
        "required": ["path", "kind", "size_bytes"],
    },
    on_failure="skip",
)
async def create_correlation_heatmap(
    ctx: SkillContext,
    *,
    table_name: str,
    name: str,
    columns: list[str] | None = None,
    title: str | None = None,
) -> dict:
    df = _require_table(ctx, table_name)
    numeric = df.select_dtypes(include="number")
    if columns is not None:
        missing = [c for c in columns if c not in numeric.columns]
        if missing:
            raise KeyError(f"Non-numeric or missing: {missing}")
        numeric = numeric[columns]
    if numeric.shape[1] < 2:
        raise ValueError(
            f"Heatmap needs >=2 numeric columns; got {numeric.shape[1]} "
            f"(available: {list(df.columns)})"
        )
    corr = numeric.corr(method="pearson")

    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(corr) + 3), max(5, 0.6 * len(corr) + 2)))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index)
    for i in range(len(corr.index)):
        for j in range(len(corr.columns)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center",
                    color="white" if abs(corr.values[i, j]) > 0.5 else "black",
                    fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title(title or "Correlation heatmap")
    return _save(fig, ctx, name)

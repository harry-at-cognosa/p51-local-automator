"""Descriptive statistics skills.

Four read-only skills that operate on tables already loaded into
ctx.tables. Used during the profile stage (deterministic) and exposed
as tools to the analyze-stage LLM (which picks what to compute).

All return JSON-friendly dicts so results travel cleanly through the
Anthropic SDK tool-use loop and through workflow_steps.output_summary.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backend.services.skills.registry import SkillContext, register


_AGG_FUNCS = ["sum", "mean", "count", "min", "max", "median", "std", "nunique"]
_CORR_METHODS = ["pearson", "kendall", "spearman"]


def _require_table(ctx: SkillContext, table_name: str) -> pd.DataFrame:
    if table_name not in ctx.tables:
        raise KeyError(f"Table {table_name!r} is not loaded. Available: {list(ctx.tables)}")
    return ctx.tables[table_name]


def _safe_float(x: Any) -> Any:
    """Convert NaN/Inf/numpy scalars to JSON-friendly forms."""
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    if hasattr(x, "item"):
        try:
            v = x.item()
        except (ValueError, TypeError):
            return str(x)
        return _safe_float(v) if isinstance(v, float) else v
    return x


@register(
    name="describe_column",
    description=(
        "Return summary statistics for a single column. For numeric columns: "
        "count, mean, std, min, quartiles, max. For categorical: count, "
        "distinct, most common value, frequency. Read-only."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
        },
        "required": ["table_name", "column"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "dtype": {"type": "string"},
            "stats": {"type": "object"},
        },
        "required": ["table_name", "column", "dtype", "stats"],
    },
    on_failure="abort",
)
async def describe_column(ctx: SkillContext, *, table_name: str, column: str) -> dict:
    df = _require_table(ctx, table_name)
    if column not in df.columns:
        raise KeyError(f"Column {column!r} not found in table {table_name!r}")
    s = df[column]
    desc = s.describe()
    stats = {k: _safe_float(v) for k, v in desc.items()}
    stats["null_count"] = int(s.isna().sum())
    return {
        "table_name": table_name,
        "column": column,
        "dtype": str(s.dtype),
        "stats": stats,
    }


@register(
    name="value_distribution",
    description=(
        "Return the top-N most frequent values in a column with absolute "
        "and percentage counts. Useful for categorical columns and for "
        "spotting outliers in low-cardinality numeric columns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "top_n": {
                "type": "integer",
                "description": "Number of most-frequent values to return.",
                "default": 20,
                "minimum": 1,
                "maximum": 200,
            },
        },
        "required": ["table_name", "column"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "total": {"type": "integer"},
            "distinct": {"type": "integer"},
            "top": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {},
                        "count": {"type": "integer"},
                        "pct": {"type": "number"},
                    },
                },
            },
        },
        "required": ["table_name", "column", "total", "distinct", "top"],
    },
    on_failure="abort",
)
async def value_distribution(
    ctx: SkillContext,
    *,
    table_name: str,
    column: str,
    top_n: int = 20,
) -> dict:
    df = _require_table(ctx, table_name)
    if column not in df.columns:
        raise KeyError(f"Column {column!r} not found in table {table_name!r}")
    s = df[column]
    total = int(len(s))
    counts = s.value_counts(dropna=False).head(top_n)
    top = [
        {
            "value": _safe_float(idx),
            "count": int(cnt),
            "pct": round(float(cnt) / total * 100.0, 2) if total else 0.0,
        }
        for idx, cnt in counts.items()
    ]
    return {
        "table_name": table_name,
        "column": column,
        "total": total,
        "distinct": int(s.nunique(dropna=True)),
        "top": top,
    }


@register(
    name="correlation_matrix",
    description=(
        "Compute a correlation matrix over the numeric columns of a table. "
        "Pearson by default; Kendall and Spearman are also supported. "
        "Non-numeric columns are skipped automatically."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "columns": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Optional whitelist; defaults to all numeric columns.",
            },
            "method": {
                "type": "string",
                "enum": _CORR_METHODS,
                "default": "pearson",
            },
        },
        "required": ["table_name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "method": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "matrix": {"type": "object"},
            "n_rows_used": {"type": "integer"},
        },
        "required": ["table_name", "method", "columns", "matrix", "n_rows_used"],
    },
    on_failure="skip",
)
async def correlation_matrix(
    ctx: SkillContext,
    *,
    table_name: str,
    columns: list[str] | None = None,
    method: str = "pearson",
) -> dict:
    if method not in _CORR_METHODS:
        raise ValueError(f"method must be one of {_CORR_METHODS}; got {method!r}")
    df = _require_table(ctx, table_name)
    numeric = df.select_dtypes(include="number")
    if columns is not None:
        missing = [c for c in columns if c not in numeric.columns]
        if missing:
            raise KeyError(
                f"Non-numeric or missing columns requested: {missing}. "
                f"Available numeric: {list(numeric.columns)}"
            )
        numeric = numeric[columns]
    corr = numeric.corr(method=method)
    matrix = {
        str(c): {str(k): _safe_float(v) for k, v in corr[c].items()}
        for c in corr.columns
    }
    return {
        "table_name": table_name,
        "method": method,
        "columns": list(map(str, corr.columns)),
        "matrix": matrix,
        "n_rows_used": int(numeric.dropna().shape[0]),
    }


@register(
    name="groupby_aggregate",
    description=(
        "Group a table by one column and compute a single aggregate over "
        "another column. Supported aggregates: sum, mean, count, min, max, "
        "median, std, nunique."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "group_by": {
                "type": "string",
                "description": "Column to group by.",
            },
            "agg_column": {
                "type": "string",
                "description": "Column to aggregate.",
            },
            "agg_func": {
                "type": "string",
                "enum": _AGG_FUNCS,
            },
        },
        "required": ["table_name", "group_by", "agg_column", "agg_func"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "group_by": {"type": "string"},
            "agg_column": {"type": "string"},
            "agg_func": {"type": "string"},
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {},
                        "value": {},
                    },
                },
            },
        },
        "required": ["table_name", "group_by", "agg_column", "agg_func", "groups"],
    },
    on_failure="abort",
)
async def groupby_aggregate(
    ctx: SkillContext,
    *,
    table_name: str,
    group_by: str,
    agg_column: str,
    agg_func: str,
) -> dict:
    if agg_func not in _AGG_FUNCS:
        raise ValueError(f"agg_func must be one of {_AGG_FUNCS}; got {agg_func!r}")
    df = _require_table(ctx, table_name)
    for c in (group_by, agg_column):
        if c not in df.columns:
            raise KeyError(f"Column {c!r} not found in table {table_name!r}")
    grouped = df.groupby(group_by)[agg_column].agg(agg_func)
    groups = [
        {"key": _safe_float(k), "value": _safe_float(v)}
        for k, v in grouped.items()
    ]
    return {
        "table_name": table_name,
        "group_by": group_by,
        "agg_column": agg_column,
        "agg_func": agg_func,
        "groups": groups,
    }

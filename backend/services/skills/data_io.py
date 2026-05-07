"""Data input/output skills.

Three skills:

- load_csv: read a CSV into ctx.tables under a given key
- load_xlsx: read an Excel sheet into ctx.tables
- write_artifact: write text or JSON content into ctx.artifacts_dir

These run during the deterministic ingest stage. The engine sanitizes
file_path to the user's sandbox before invoking — these skills trust
what they're handed.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from backend.services.skills.registry import SkillContext, register


def _df_metadata(df: pd.DataFrame) -> dict:
    return {
        "rows": int(df.shape[0]),
        "columns": list(df.columns.astype(str)),
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
    }


@register(
    name="load_csv",
    description=(
        "Load a CSV file into the workflow's tables dict under the given "
        "table_name. Subsequent skills reference the data by table_name."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Key under which to register the loaded DataFrame.",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the CSV file.",
            },
        },
        "required": ["table_name", "file_path"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "dtypes": {"type": "object"},
        },
        "required": ["rows", "columns", "dtypes"],
    },
    on_failure="abort",
)
async def load_csv(ctx: SkillContext, *, table_name: str, file_path: str) -> dict:
    df = pd.read_csv(file_path)
    ctx.tables[table_name] = df
    return _df_metadata(df)


@register(
    name="load_xlsx",
    description=(
        "Load an XLSX worksheet into the workflow's tables dict under the "
        "given table_name. If sheet_name is omitted the first sheet is read."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "file_path": {"type": "string"},
            "sheet_name": {
                "type": ["string", "null"],
                "description": "Sheet to load. Defaults to the first sheet.",
            },
        },
        "required": ["table_name", "file_path"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "dtypes": {"type": "object"},
            "sheet_name": {"type": "string"},
        },
        "required": ["rows", "columns", "dtypes", "sheet_name"],
    },
    on_failure="abort",
)
async def load_xlsx(
    ctx: SkillContext,
    *,
    table_name: str,
    file_path: str,
    sheet_name: str | None = None,
) -> dict:
    # pd.read_excel returns a DataFrame when sheet_name is a string or 0;
    # passing None reads the first sheet (default behavior).
    if sheet_name is None:
        # Determine the actual first-sheet name for the response payload.
        with pd.ExcelFile(file_path) as xls:
            actual = xls.sheet_names[0]
        df = pd.read_excel(file_path, sheet_name=actual)
    else:
        actual = sheet_name
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    ctx.tables[table_name] = df
    out = _df_metadata(df)
    out["sheet_name"] = actual
    return out


@register(
    name="write_artifact",
    description=(
        "Write text or JSON content to the run's artifacts directory. "
        "Use for non-chart outputs (computed CSVs, JSON metadata, "
        "markdown notes). String content is written as-is; objects are "
        "JSON-serialized with indent=2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Output filename (basename only, no directories).",
            },
            "content": {
                "description": "String body, or an object/list to JSON-serialize.",
            },
            "kind": {
                "type": "string",
                "description": "Free-form label (json, csv, md, txt) for the engine artifact record.",
                "default": "text",
            },
        },
        "required": ["name", "content"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "kind": {"type": "string"},
        },
        "required": ["path", "size_bytes", "kind"],
    },
    on_failure="abort",
)
async def write_artifact(
    ctx: SkillContext,
    *,
    name: str,
    content: Any,
    kind: str = "text",
) -> dict:
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise ValueError(f"write_artifact name must be a basename, got {name!r}")
    path = os.path.join(ctx.artifacts_dir, name)
    if isinstance(content, (dict, list)):
        body = json.dumps(content, indent=2, default=str)
    elif isinstance(content, str):
        body = content
    else:
        raise TypeError(
            f"write_artifact content must be str, dict, or list; got {type(content).__name__}"
        )
    os.makedirs(ctx.artifacts_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return {
        "path": path,
        "size_bytes": len(body.encode("utf-8")),
        "kind": kind,
    }

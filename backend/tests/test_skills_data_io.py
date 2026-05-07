"""Hermetic unit tests for data_io skills.

Test fixtures are generated synthetically via tmp_path — no dependency
on docs/wrkfl_*.xlsx or any external file. Each test builds the input,
calls the skill, and asserts both the return value and the side effect
(ctx.tables population, file write).

Run with: pytest backend/tests/test_skills_data_io.py -v
"""
import json
import os

import pandas as pd
import pytest

from backend.services.skills.data_io import load_csv, load_xlsx, write_artifact
from backend.services.skills.registry import SKILL_REGISTRY, SkillContext


def _make_ctx(tmp_path) -> SkillContext:
    return SkillContext(run_id=1, artifacts_dir=str(tmp_path / "artifacts"))


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "name": ["a", "b", "c", "d"],
            "amount": [10.5, 20.0, 30.25, 40.75],
        }
    )


# ── load_csv ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_csv_populates_tables_and_returns_metadata(tmp_path):
    csv_path = tmp_path / "data.csv"
    _sample_df().to_csv(csv_path, index=False)
    ctx = _make_ctx(tmp_path)

    result = await load_csv(ctx, table_name="orders", file_path=str(csv_path))

    assert "orders" in ctx.tables
    assert ctx.tables["orders"].shape == (4, 3)
    assert result["rows"] == 4
    assert result["columns"] == ["id", "name", "amount"]
    assert "amount" in result["dtypes"]


@pytest.mark.asyncio
async def test_load_csv_raises_on_missing_file(tmp_path):
    ctx = _make_ctx(tmp_path)
    with pytest.raises(FileNotFoundError):
        await load_csv(ctx, table_name="x", file_path=str(tmp_path / "nope.csv"))


# ── load_xlsx ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_xlsx_default_first_sheet(tmp_path):
    xlsx_path = tmp_path / "data.xlsx"
    with pd.ExcelWriter(xlsx_path) as w:
        _sample_df().to_excel(w, sheet_name="Orders", index=False)
    ctx = _make_ctx(tmp_path)

    result = await load_xlsx(ctx, table_name="orders", file_path=str(xlsx_path))

    assert ctx.tables["orders"].shape == (4, 3)
    assert result["sheet_name"] == "Orders"


@pytest.mark.asyncio
async def test_load_xlsx_explicit_sheet(tmp_path):
    xlsx_path = tmp_path / "multi.xlsx"
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"b": [10, 20, 30]})
    with pd.ExcelWriter(xlsx_path) as w:
        df1.to_excel(w, sheet_name="Sheet1", index=False)
        df2.to_excel(w, sheet_name="Customers", index=False)
    ctx = _make_ctx(tmp_path)

    result = await load_xlsx(
        ctx, table_name="cust", file_path=str(xlsx_path), sheet_name="Customers"
    )

    assert ctx.tables["cust"].shape == (3, 1)
    assert result["sheet_name"] == "Customers"
    assert result["columns"] == ["b"]


# ── write_artifact ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_artifact_string_content(tmp_path):
    ctx = _make_ctx(tmp_path)
    body = "# Report\n\nFindings: many."

    result = await write_artifact(ctx, name="report.md", content=body, kind="md")

    assert result["kind"] == "md"
    assert result["path"].endswith("report.md")
    assert os.path.exists(result["path"])
    with open(result["path"]) as f:
        assert f.read() == body
    assert result["size_bytes"] == len(body.encode("utf-8"))


@pytest.mark.asyncio
async def test_write_artifact_dict_serializes_to_json(tmp_path):
    ctx = _make_ctx(tmp_path)
    payload = {"summary": "ok", "metrics": {"rows": 100}}

    result = await write_artifact(ctx, name="meta.json", content=payload, kind="json")

    with open(result["path"]) as f:
        assert json.load(f) == payload


@pytest.mark.asyncio
async def test_write_artifact_creates_dir_if_missing(tmp_path):
    ctx = _make_ctx(tmp_path)
    assert not os.path.exists(ctx.artifacts_dir)

    await write_artifact(ctx, name="x.txt", content="hi")

    assert os.path.isdir(ctx.artifacts_dir)


@pytest.mark.asyncio
async def test_write_artifact_rejects_path_traversal(tmp_path):
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="basename"):
        await write_artifact(ctx, name="../escape.txt", content="x")
    with pytest.raises(ValueError, match="basename"):
        await write_artifact(ctx, name="sub/dir.txt", content="x")


@pytest.mark.asyncio
async def test_write_artifact_rejects_bytes(tmp_path):
    ctx = _make_ctx(tmp_path)
    with pytest.raises(TypeError):
        await write_artifact(ctx, name="x.bin", content=b"binary")


# ── registry wiring ──────────────────────────────────────────────────


def test_data_io_skills_are_registered():
    """data_io @register decorators populate SKILL_REGISTRY at import time."""
    assert "load_csv" in SKILL_REGISTRY
    assert "load_xlsx" in SKILL_REGISTRY
    assert "write_artifact" in SKILL_REGISTRY
    assert SKILL_REGISTRY["load_csv"].on_failure == "abort"

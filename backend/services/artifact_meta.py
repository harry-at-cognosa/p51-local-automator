"""Self-describing artifact metadata — every artifact carries a block
identifying which run produced it and what subject it covers.

Two public surfaces:

  1. `build_artifact_meta(workflow, run, *, kind, filename)` — returns a
     plain dict combining (a) common fields shared across every
     workflow type and (b) a per-type Subject block.

  2. Format wrappers — each applies the meta dict to file content
     appropriate to that format:
        wrap_json(meta, payload)         → dict with __meta__ first
        wrap_markdown(meta, body)        → YAML frontmatter + body
        wrap_excel_workbook(meta, wb)    → inserts Provenance as sheet 0
        wrap_csv_bytes(meta, csv_body)   → leading #-comment lines + body
        chart_footer_text(meta)          → short one-liner for matplotlib

These run in two contexts:
  - In-process (backend runners) — full meta dict from build_artifact_meta.
  - Subprocess scripts (analyze_data.py, email_to_excel.py) — meta dict
    delivered via --meta-json CLI flag; scripts call the wrappers
    directly (duplicated stubs inside the script files for portability).

Per the design memo, no backfill — artifacts produced before this
commit are untouched.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.db.models import UserWorkflows, WorkflowRuns


# ── Subject adapters: one per workflow type_id ───────────────────────


def _subject_email_workflow(config: dict) -> dict:
    """Types 1 (Email Topic Monitor), 5 (Auto-Reply Draft), 6 (Auto-Reply
    Approve). Returns the list of human-readable account labels."""
    # Lazy import to avoid circulars during module load.
    from backend.services.workflows.email_monitor import _account_label, _resolve_accounts
    try:
        accounts = _resolve_accounts(config)
    except Exception:
        # Single-account legacy shape that _resolve_accounts can't handle.
        return {}
    return {"accounts": [_account_label(a) for a in accounts]}


def _subject_data_analyzer(config: dict) -> dict:
    """Type 2 — single input file."""
    raw = config.get("file_path")
    if isinstance(raw, dict):
        path = raw.get("path") or ""
    elif isinstance(raw, str):
        path = raw
    else:
        path = ""
    return {"file": path}


def _subject_calendar_digest(config: dict) -> dict:
    """Type 3. Apple uses local calendars by name; Google uses an
    account_id reference."""
    service = config.get("service", "apple_calendar")
    if service == "google_calendar":
        # Account id is the FK; the runner enriches with email at run
        # time — we record both when available, just the id otherwise.
        out: dict[str, Any] = {"service": "google_calendar"}
        account_id = config.get("account_id")
        if isinstance(account_id, int):
            out["account_id"] = account_id
        email = config.get("_resolved_email") or config.get("email")
        if isinstance(email, str) and email:
            out["account"] = email
        return out
    calendars = config.get("calendars") or []
    if not isinstance(calendars, list):
        calendars = []
    return {"calendars": list(calendars)}


_CONNSTR_RE = re.compile(
    r"""^[a-zA-Z+]+://      # scheme like postgresql+asyncpg://
        (?:[^:@/]+(?::[^@/]*)?@)?  # optional user:pass@
        (?P<host>[^:/?]+)          # host
        (?::(?P<port>\d+))?         # optional :port
        (?:/(?P<db>[^/?]*))?        # optional /db
    """,
    re.VERBOSE,
)


def _connection_label(connection_string: str | None) -> str:
    """Parse host[:port][/db] from a connection string. NEVER returns
    the password. Falls back to a placeholder for shapes we don't
    recognize."""
    if not isinstance(connection_string, str) or not connection_string:
        return "[unset]"
    m = _CONNSTR_RE.match(connection_string)
    if not m:
        return "[unparsed connection]"
    parts = [m.group("host") or "?"]
    if m.group("port"):
        parts[0] = f"{parts[0]}:{m.group('port')}"
    if m.group("db"):
        parts.append(f"/{m.group('db')}")
    return "".join(parts)


def _subject_sql_runner(config: dict) -> dict:
    """Type 4 — query name + a connection label (NEVER the connection
    string itself, which carries the password)."""
    return {
        "query_name": (config.get("query_name") or "[unnamed]").strip() or "[unnamed]",
        "connection_label": _connection_label(config.get("connection_string")),
    }


def _subject_awf1(config: dict) -> dict:
    """Type 7 — list of data_definition tables with their files."""
    raw = config.get("data_definition") or []
    if not isinstance(raw, list):
        return {"tables": []}
    tables: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("table_name") or ""
        file_raw = entry.get("file") or entry.get("file_path")
        if isinstance(file_raw, dict):
            file_path = file_raw.get("path") or ""
        elif isinstance(file_raw, str):
            file_path = file_raw
        else:
            file_path = ""
        tables.append({"name": str(name), "file": file_path})
    return {"tables": tables}


_SUBJECT_ADAPTERS = {
    1: _subject_email_workflow,
    2: _subject_data_analyzer,
    3: _subject_calendar_digest,
    4: _subject_sql_runner,
    5: _subject_email_workflow,
    6: _subject_email_workflow,
    7: _subject_awf1,
}


# ── Public meta builder ───────────────────────────────────────────────


def build_artifact_meta(
    workflow: UserWorkflows,
    run: WorkflowRuns,
    *,
    kind: str | None = None,
    filename: str | None = None,
) -> dict:
    """Compose the metadata dict for an artifact about to be written.

    `kind` and `filename` are informational; consumers (especially humans
    opening the file later) appreciate knowing which file they're
    looking at. Per the design memo, no per-format mutation happens
    here — that's the wrappers' job.
    """
    type_long_name = ""
    type_id = workflow.type_id
    if workflow.workflow_type is not None:
        type_long_name = workflow.workflow_type.long_name or workflow.workflow_type.type_name or ""

    user_name = ""
    group_name = ""
    if workflow.user is not None:
        user_name = workflow.user.user_name or ""
        if workflow.user.group is not None:
            group_name = workflow.user.group.short_name or ""

    started_at = (run.started_at or datetime.now(timezone.utc))
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    meta: dict[str, Any] = {
        "Workflow":      type_long_name,
        "Workflow name": workflow.name or "",
        "Workflow ID":   workflow.workflow_id,
        "Run ID":        run.run_id,
        "Generated at":  started_at.isoformat(),
    }
    if filename:
        meta["Filename"] = filename
    if user_name:
        meta["User"] = user_name
    if group_name:
        meta["Group"] = group_name

    adapter = _SUBJECT_ADAPTERS.get(type_id)
    if adapter is not None:
        try:
            subject = adapter(workflow.config or {})
        except Exception:
            subject = {}
        if subject:
            meta["Subject"] = subject

    if kind:
        meta["Kind"] = kind
    return meta


# ── Format wrappers ───────────────────────────────────────────────────


def wrap_json(meta: Mapping[str, Any], payload: Any) -> Any:
    """Insert `__meta__` as the first key of an object payload. If the
    payload is a list (or anything other than a dict), wrap it in a
    new dict so the meta block still appears."""
    if isinstance(payload, dict):
        out: dict[str, Any] = {"__meta__": dict(meta)}
        out.update(payload)
        return out
    return {"__meta__": dict(meta), "data": payload}


def _meta_to_yaml_lines(meta: Mapping[str, Any], indent: int = 0) -> list[str]:
    """Tiny YAML emitter — handles strings, ints, bools, lists, and
    nested dicts (one level). Quotes only when the value contains a
    YAML-significant character. Avoids pyyaml dependency."""
    lines: list[str] = []
    pad = "  " * indent
    for key, value in meta.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_meta_to_yaml_lines(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
                continue
            lines.append(f"{pad}{key}:")
            for item in value:
                if isinstance(item, dict):
                    # Render the first key inline with the dash, the rest indented.
                    items = list(item.items())
                    first_k, first_v = items[0]
                    lines.append(f"{pad}  - {first_k}: {_yaml_scalar(first_v)}")
                    for k, v in items[1:]:
                        lines.append(f"{pad}    {k}: {_yaml_scalar(v)}")
                else:
                    lines.append(f"{pad}  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(value)}")
    return lines


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    s = str(value)
    if any(ch in s for ch in ":#&*?{}[]|>%@`,'\"") or s.strip() != s or not s:
        # Quote and escape inner quotes.
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def wrap_markdown(meta: Mapping[str, Any], body: str) -> str:
    """Prepend a YAML frontmatter block to a markdown body."""
    lines = ["---"]
    lines.extend(_meta_to_yaml_lines(meta))
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n" + (body or "")


def wrap_csv_bytes(meta: Mapping[str, Any], csv_body: str) -> str:
    """Prepend `#`-comment lines to a CSV body so pandas read_csv with
    `comment='#'` reads it cleanly. Multi-line values are flattened to
    a single line."""
    out: list[str] = []
    for key, value in meta.items():
        if isinstance(value, (dict, list)):
            # Render compactly via JSON so a single line carries the whole subject.
            value_str = json.dumps(value, default=str)
        else:
            value_str = str(value)
        value_str = value_str.replace("\n", " ").replace("\r", " ")
        out.append(f"# {key}: {value_str}")
    return "\n".join(out) + "\n" + (csv_body or "")


def wrap_excel_workbook(meta: Mapping[str, Any], wb) -> None:
    """Insert a Provenance sheet as the FIRST sheet of an openpyxl
    Workbook. Mutates the workbook in place; caller saves afterward.

    Trade-off documented in the plan: putting Provenance first means a
    human opening the file sees the metadata immediately, but
    `pd.read_excel(path)` (no sheet_name arg) reads metadata instead
    of data. Downstream consumers must specify the data sheet by name.
    """
    # openpyxl: create_sheet at index 0 puts it first.
    if "Provenance" in wb.sheetnames:
        del wb["Provenance"]
    ws = wb.create_sheet("Provenance", 0)
    ws.append(["Field", "Value"])
    for key, value in meta.items():
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, default=str)
        else:
            value_str = str(value)
        ws.append([key, value_str])
    # Make the active sheet the SECOND one (the real data) when there
    # is one, so opening the file in Excel still shows the data first.
    # If Provenance is the only sheet, leave it active.
    if len(wb.sheetnames) > 1:
        wb.active = 1


def chart_footer_text(meta: Mapping[str, Any]) -> str:
    """One-line summary suitable for matplotlib `fig.text(...)` at the
    bottom of a chart. Compact: workflow name + subject one-liner."""
    name = meta.get("Workflow name") or meta.get("Workflow") or "workflow"
    subject = meta.get("Subject") or {}
    bits: list[str] = [str(name)]
    if isinstance(subject, dict):
        if "accounts" in subject:
            accs = subject["accounts"]
            if isinstance(accs, list):
                bits.append(", ".join(str(a) for a in accs))
        elif "file" in subject:
            bits.append(str(subject["file"]))
        elif "calendars" in subject:
            cals = subject["calendars"]
            if isinstance(cals, list):
                bits.append(", ".join(str(c) for c in cals))
        elif "account" in subject:
            bits.append(str(subject["account"]))
        elif "tables" in subject:
            tables = subject["tables"]
            if isinstance(tables, list):
                bits.append(", ".join(str(t.get("name") or t.get("file") or "?") for t in tables if isinstance(t, dict)))
        elif "query_name" in subject:
            bits.append(str(subject["query_name"]))
    run_id = meta.get("Run ID")
    if run_id is not None:
        bits.append(f"run #{run_id}")
    return " — ".join(bits)

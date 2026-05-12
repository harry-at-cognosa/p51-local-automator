#!/usr/bin/env python3
"""Migrate Type 2 workflows' config.file_path to the inputs sandbox shape.

Phase T2S.3 — companion to the T2S.1 backend sandboxing and the T2S.2
frontend FilePicker.

Buckets each Type 2 row's current file_path into:

  relative              Already a {path, name} dict OR a relative
                        string. No action.
  absolute_under_inputs Absolute path that begins with the user's
                        inputs root. Rewrite to {path: rel, name: basename}.
  absolute_elsewhere    Absolute path outside any inputs root. Flag
                        for manual fix-up; not auto-rewritten.
  empty                 file_path missing or empty. Leave alone — the
                        workflow is already broken regardless.

Read-only by default. Pass --apply to commit the absolute_under_inputs
rewrites in a single transaction.

Resolves file_system_root via the same chain the backend uses:
  group_settings(group_id, 'file_system_root')   →
  api_settings('file_system_root')               →  error.

Usage:
    python3 scripts/migrate_type2_file_paths.py
    python3 scripts/migrate_type2_file_paths.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2
import psycopg2.extras


DSN_ENV = "DATABASE_URL"
DEFAULT_DSN = "postgresql://localhost/p51_automator"


def _connect(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.set_session(autocommit=False)
    return conn


def _load_file_system_roots(cur) -> tuple[str | None, dict[int, str]]:
    """Return (global_default, per_group_override_map). Either may be
    absent; the caller fails per-row if it can't resolve."""
    cur.execute("SELECT value FROM api_settings WHERE name = 'file_system_root'")
    row = cur.fetchone()
    global_default = row[0] if row else None

    cur.execute(
        "SELECT group_id, value FROM group_settings WHERE name = 'file_system_root'"
    )
    overrides = {gid: val for gid, val in cur.fetchall()}
    return global_default, overrides


def _user_inputs_root(
    group_id: int,
    user_id: int,
    global_default: str | None,
    overrides: dict[int, str],
) -> str | None:
    base = overrides.get(group_id) or global_default
    if not base:
        return None
    return os.path.normpath(os.path.join(base, str(group_id), str(user_id), "inputs"))


def _classify(
    fp,
    inputs_root: str | None,
) -> tuple[str, dict | None]:
    """Return (bucket, new_value_dict_or_None).

    new_value is only non-None for absolute_under_inputs (the rewrite target).
    """
    if fp in (None, "", {}):
        return "empty", None
    if isinstance(fp, dict):
        # Already the new shape (or close enough). Don't rewrite.
        return "relative", None
    if not isinstance(fp, str):
        return "empty", None
    s = fp.strip()
    if not s:
        return "empty", None
    if not os.path.isabs(s):
        return "relative", None
    # Absolute: see if it's under the user's inputs root.
    if inputs_root is None:
        return "absolute_elsewhere", None
    s_norm = os.path.normpath(s)
    if s_norm == inputs_root or s_norm.startswith(inputs_root + os.sep):
        rel = os.path.relpath(s_norm, inputs_root)
        return "absolute_under_inputs", {"path": rel, "name": os.path.basename(rel)}
    return "absolute_elsewhere", None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="commit rewrites")
    ap.add_argument(
        "--dsn",
        default=os.environ.get(DSN_ENV, DEFAULT_DSN),
        help="Postgres DSN (default from $DATABASE_URL or %(default)r)",
    )
    args = ap.parse_args()

    conn = _connect(args.dsn)
    try:
        cur = conn.cursor()
        global_default, overrides = _load_file_system_roots(cur)
        if not global_default and not overrides:
            print(
                "ERROR: file_system_root is not configured in api_settings or "
                "group_settings; cannot resolve any user's inputs root.",
                file=sys.stderr,
            )
            return 2

        cur.execute(
            "SELECT workflow_id, user_id, group_id, name, config "
            "FROM user_workflows WHERE type_id = 2 AND deleted = 0 "
            "ORDER BY workflow_id"
        )
        rows = cur.fetchall()

        buckets = {"relative": [], "absolute_under_inputs": [], "absolute_elsewhere": [], "empty": []}
        rewrites = []  # (workflow_id, new_file_path_dict)

        for workflow_id, user_id, group_id, name, config in rows:
            cfg = config or {}
            fp = cfg.get("file_path")
            inputs_root = _user_inputs_root(group_id, user_id, global_default, overrides)
            bucket, new_value = _classify(fp, inputs_root)
            buckets[bucket].append(
                {
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                    "group_id": group_id,
                    "name": name,
                    "file_path": fp,
                    "inputs_root": inputs_root,
                }
            )
            if bucket == "absolute_under_inputs" and new_value is not None:
                new_cfg = dict(cfg)
                new_cfg["file_path"] = new_value
                rewrites.append((workflow_id, new_cfg))

        # Report.
        print("=" * 70)
        print(f"Type 2 file_path migration — {'APPLY' if args.apply else 'DRY-RUN'}")
        print("=" * 70)
        for bucket, items in buckets.items():
            print(f"  {bucket:25s}  {len(items)} row(s)")
        print()

        if buckets["absolute_under_inputs"]:
            print("Will rewrite (absolute_under_inputs):")
            for r in buckets["absolute_under_inputs"]:
                print(
                    f"  wf {r['workflow_id']:>4d}  user {r['user_id']}  "
                    f"group {r['group_id']}  {r['name']!r}"
                )
                print(f"      from: {r['file_path']}")
                # Find the matching rewrite tuple for display
                for wid, new_cfg in rewrites:
                    if wid == r["workflow_id"]:
                        print(f"      to:   {new_cfg['file_path']}")
                        break
            print()

        if buckets["absolute_elsewhere"]:
            print("Manual fix-up needed (absolute_elsewhere):")
            for r in buckets["absolute_elsewhere"]:
                print(
                    f"  wf {r['workflow_id']:>4d}  user {r['user_id']}  "
                    f"group {r['group_id']}  {r['name']!r}"
                )
                print(f"      file_path: {r['file_path']}")
                print(
                    f"      not under: {r['inputs_root'] or '(no inputs root resolvable)'}"
                )
            print(
                "\n  → Copy these files under each user's inputs root, then "
                "edit the workflow via the UI Pick file button."
            )
            print()

        if not args.apply:
            print("Dry-run complete. Re-run with --apply to commit rewrites.")
            return 0

        if not rewrites:
            print("Nothing to apply.")
            return 0

        for workflow_id, new_cfg in rewrites:
            cur.execute(
                "UPDATE user_workflows SET config = %s WHERE workflow_id = %s",
                (json.dumps(new_cfg), workflow_id),
            )
        conn.commit()
        print(f"Applied {len(rewrites)} rewrite(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

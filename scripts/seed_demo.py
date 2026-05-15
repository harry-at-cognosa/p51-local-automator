"""Seed a Demo group + demo_user pre-loaded with the five sample workflows.

Idempotent: re-running upserts and skips existing rows / files. Intended to
be run once on a fresh install to give a Mac Mini admin something runnable
within 30 seconds of `alembic upgrade head`.

Source-of-fixtures contract: --source-dir must contain the same subfolder
layout the demo workflows reference:

  <source-dir>/uci_online_retail/online_retail_II.xlsx
  <source-dir>/uci_online_retail/online_retail_2009_2010.csv
  <source-dir>/uci_online_retail/online_retail_2010_2011.csv
  <source-dir>/nyc311/nyc311_manhattan_2024_sample.csv
  <source-dir>/cuad_contracts/master_clauses.csv
  <source-dir>/cuad_contracts/contracts_metadata.csv
  <source-dir>/enron/enron_emails_sample.csv

Producing those derived files from upstream raw downloads (slicing NYC,
converting Enron parquet, deriving CUAD metadata, splitting UCI sheets)
is a separate concern — write a one-time prepare-fixtures script if you
want the upstream-to-staged transform automated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from backend.auth.users import password_helper  # noqa: E402
from backend.db.models import (  # noqa: E402
    ApiGroups,
    GroupSettings,
    User,
    UserWorkflows,
)
from backend.db.session import SqlAsyncSession, sql_async_engine  # noqa: E402


# ── Fixture catalog ────────────────────────────────────────────────

FIXTURES: list[tuple[str, str]] = [
    # (source-relative path, destination-relative path under <inputs>/)
    ("uci_online_retail/online_retail_II.xlsx",       "uci_online_retail/online_retail_II.xlsx"),
    ("uci_online_retail/online_retail_2009_2010.csv", "uci_online_retail/online_retail_2009_2010.csv"),
    ("uci_online_retail/online_retail_2010_2011.csv", "uci_online_retail/online_retail_2010_2011.csv"),
    ("nyc311/nyc311_manhattan_2024_sample.csv",       "nyc311/nyc311_manhattan_2024_sample.csv"),
    ("cuad_contracts/master_clauses.csv",             "cuad_contracts/master_clauses.csv"),
    ("cuad_contracts/contracts_metadata.csv",         "cuad_contracts/contracts_metadata.csv"),
    ("enron/enron_emails_sample.csv",                 "enron/enron_emails_sample.csv"),
]


# ── Workflow specs ─────────────────────────────────────────────────
# Kept verbatim from the manual seeds; the seed script is the canonical
# source of these specs for fresh installs.

def _workflow_specs() -> list[dict]:
    return [
        {
            "type_id": 2,
            "name": "Demo — UCI Online Retail II (UK e-commerce transactions)",
            "config": {
                "file_path": {"path": "uci_online_retail/online_retail_II.xlsx",
                              "name": "online_retail_II.xlsx"},
                "output_format": "xlsx",
                "key_fields": ["InvoiceDate", "Country", "Description",
                               "Quantity", "UnitPrice", "CustomerID"],
            },
        },
        {
            "type_id": 2,
            "name": "Demo — NYC 311 Manhattan 2024 (Sep–Dec service requests)",
            "config": {
                "file_path": {"path": "nyc311/nyc311_manhattan_2024_sample.csv",
                              "name": "nyc311_manhattan_2024_sample.csv"},
                "output_format": "xlsx",
                "key_fields": ["created_date", "complaint_type", "agency",
                               "borough", "status"],
            },
        },
        {
            "type_id": 2,
            "name": "Demo — Enron emails 2000–2001 (sender/topic patterns)",
            "config": {
                "file_path": {"path": "enron/enron_emails_sample.csv",
                              "name": "enron_emails_sample.csv"},
                "output_format": "xlsx",
                "key_fields": ["date", "from", "to", "cc", "subject",
                               "body_truncated"],
            },
        },
        {
            "type_id": 7,
            "name": "Demo — CUAD contracts (clause variance by category)",
            "config": {
                "analysis_goal": (
                    "Across this corpus of 510 real commercial contracts, characterize how "
                    "clause patterns vary by contract category (e.g. Distribution, License, "
                    "Service, Strategic Alliance). Focus on clauses with material legal/economic "
                    "impact: Cap On Liability, Uncapped Liability, Governing Law, IP Ownership "
                    "Assignment, License Grant, Non-Compete, Exclusivity, Anti-Assignment, "
                    "Change Of Control, Renewal Term, and Notice Period To Terminate Renewal. "
                    "Identify categories that systematically over- or under-use specific clauses, "
                    "and call out any surprising patterns."
                ),
                "report_structure": (
                    "1. Corpus overview — number of contracts, categories represented, top 5 by size.\n"
                    "2. Clause-presence matrix — per focus clause, which categories show it most/least.\n"
                    "3. Governing-law geography — top jurisdictions overall and category-level skew.\n"
                    "4. Surprising patterns — 3–5 bullets a contract attorney would flag.\n"
                    "5. Methodological caveats — what master_clauses captures and what it doesn't."
                ),
                "voice_and_style": (
                    "Plain English, attorney-friendly. Cite category names exactly as they appear. "
                    "Use percentages with whole-number precision. Avoid hedging unless the data "
                    "genuinely doesn't support a claim — then say so directly."
                ),
                "report_filename": "cuad_clause_variance_by_category",
                "processing_steps": (
                    "1. Ingest master_clauses and contracts_metadata; use descriptions to understand each.\n"
                    "2. Join the two on Filename (case-insensitive stem if needed).\n"
                    "3. For each focus clause, compute presence by category. Spot-check the answer column.\n"
                    "4. Produce per-clause and per-category summary tables; chart only where it adds clarity.\n"
                    "5. Synthesize a category-level narrative — which cluster, which stand apart, why."
                ),
                "data_definition": [
                    {"file": {"path": "cuad_contracts/master_clauses.csv",
                              "name": "master_clauses.csv"},
                     "description": (
                        "CUAD master clauses table: one row per contract (510 total), ~80 columns "
                        "covering ~40 clause categories. Each clause has two columns: <ClauseName> "
                        "(extracted text) and <ClauseName>-Answer (Yes/No or matched span). Filename "
                        "is the join key."
                     )},
                    {"file": {"path": "cuad_contracts/contracts_metadata.csv",
                              "name": "contracts_metadata.csv"},
                     "description": (
                        "Derived metadata per contract: Filename (join key), part (Part_I / Part_II / "
                        "Part_III), contract_category (e.g. Distributor, License_Agreements, Strategic "
                        "Alliance), family (a coarser grouping). Source: CUAD PDF directory tree."
                     )},
                ],
            },
        },
        {
            "type_id": 7,
            "name": "Demo — UCI Online Retail (year-over-year, 2009-10 vs 2010-11)",
            "config": {
                "analysis_goal": (
                    "Compare UK e-commerce activity between the 2009-2010 fiscal window "
                    "(Dec 2009 – Dec 2010) and 2010-2011 (Dec 2010 – Dec 2011). Quantify YoY change "
                    "in total revenue, order volume, average order value, return rate, customer "
                    "count, and country mix. Identify any country or stock-code family that drove "
                    "a disproportionate share of the shift. Treat anonymous customers as a separate "
                    "cohort."
                ),
                "report_structure": (
                    "1. Headline YoY deltas (revenue, orders, AOV, returns, customers, countries).\n"
                    "2. Country mix — top 10 by revenue per year, with rank changes.\n"
                    "3. Returns analysis by year and country.\n"
                    "4. Anonymous-customer cohort share YoY.\n"
                    "5. Notable inflection points — months with sharply non-uniform YoY delta.\n"
                    "6. Caveats — data quality, definition choices."
                ),
                "voice_and_style": (
                    "Analyst tone. Numbers up front, narrative second. Whole-dollar totals, one-decimal "
                    "percentages. No celebratory language — this is comparison, not marketing."
                ),
                "report_filename": "uci_retail_yoy_2010_vs_2011",
                "processing_steps": (
                    "1. Load both year tables; confirm schema and date coverage per the descriptions.\n"
                    "2. Compute per-year summaries (rows, date span, revenue, orders, AOV, returns, "
                    "unique customers including the null cohort, unique Country).\n"
                    "3. Build a country × year revenue table; rank top 10 each year and compare.\n"
                    "4. Build monthly-revenue time series per year aligned on calendar month.\n"
                    "5. Synthesize. Generate charts only where they help; skip on string-only columns."
                ),
                "data_definition": [
                    {"file": {"path": "uci_online_retail/online_retail_2009_2010.csv",
                              "name": "online_retail_2009_2010.csv"},
                     "description": (
                        "UCI Online Retail II — 2009-2010 sheet as CSV. 525,461 rows covering "
                        "Dec 2009 – Dec 2010 for one UK online retailer. Columns: Invoice, "
                        "StockCode, Description, Quantity, InvoiceDate, Price, Customer ID, "
                        "Country. Negative Quantity = returns. Customer ID null = guest."
                     )},
                    {"file": {"path": "uci_online_retail/online_retail_2010_2011.csv",
                              "name": "online_retail_2010_2011.csv"},
                     "description": (
                        "UCI Online Retail II — 2010-2011 sheet as CSV. 541,910 rows covering "
                        "Dec 2010 – Dec 2011 (same retailer, same schema as 2009-2010). The two "
                        "files overlap in December 2010 — treat each row by InvoiceDate to avoid "
                        "double-counting if you union them."
                     )},
                ],
            },
        },
    ]


# ── Operations ─────────────────────────────────────────────────────


async def _upsert_group(session: AsyncSession, name: str) -> ApiGroups:
    grp = (
        await session.execute(select(ApiGroups).where(ApiGroups.group_name == name, ApiGroups.deleted == 0))
    ).scalar_one_or_none()
    if grp:
        print(f"[seed-demo] group {name!r} exists (group_id={grp.group_id})")
        return grp
    grp = ApiGroups(group_name=name)
    session.add(grp)
    await session.flush()
    print(f"[seed-demo] created group {name!r} (group_id={grp.group_id})")
    return grp


async def _upsert_user(session: AsyncSession, group: ApiGroups, user_name: str,
                       password: str, full_name: str) -> User:
    u = (
        await session.execute(select(User).where(User.user_name == user_name, User.deleted == 0))
    ).scalar_one_or_none()
    if u:
        print(f"[seed-demo] user {user_name!r} exists (user_id={u.user_id}, group_id={u.group_id})")
        if u.group_id != group.group_id:
            print(f"[seed-demo]   WARNING: existing user belongs to group_id={u.group_id}, "
                  f"not the demo group {group.group_id}")
        return u
    u = User(
        id=uuid.uuid4(),
        email=f"{user_name}@demo.local",
        user_name=user_name,
        full_name=full_name,
        hashed_password=password_helper.hash(password),
        group_id=group.group_id,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        is_groupadmin=False,
        is_manager=True,
    )
    session.add(u)
    await session.flush()
    print(f"[seed-demo] created user {user_name!r} (user_id={u.user_id})")
    return u


async def _upsert_group_setting(session: AsyncSession, group_id: int, name: str, value: str) -> None:
    existing = (
        await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group_id, GroupSettings.name == name)
        )
    ).scalar_one_or_none()
    if existing:
        if existing.value != value:
            print(f"[seed-demo] group_setting {name!r} differs ({existing.value!r} → {value!r}); leaving as-is")
        else:
            print(f"[seed-demo] group_setting {name!r}={value!r} already set")
        return
    session.add(GroupSettings(group_id=group_id, name=name, value=value))
    print(f"[seed-demo] set group_setting {name!r}={value!r}")


def _copy_fixtures(source_dir: Path, inputs_dir: Path) -> tuple[int, int]:
    """Copy each fixture in FIXTURES from source_dir to inputs_dir.

    Returns (copied, skipped) counts. Missing source files print a warning
    but don't abort — the workflow row still gets created so the admin can
    drop the file in later and re-run.
    """
    copied = skipped = 0
    for src_rel, dst_rel in FIXTURES:
        src = source_dir / src_rel
        dst = inputs_dir / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            print(f"[seed-demo] MISSING source fixture: {src}  (workflow will fail until staged)")
            continue
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
        print(f"[seed-demo] copied {src_rel} → {dst}")
    return copied, skipped


async def _upsert_workflows(session: AsyncSession, user: User, specs: list[dict]) -> int:
    """Insert any workflow spec that doesn't already exist for this user.

    De-dup key is (user_id, type_id, name). Existing rows are left untouched
    — re-running the seed never overwrites a workflow the admin may have
    tuned manually.
    """
    n_created = 0
    for spec in specs:
        existing = (
            await session.execute(
                select(UserWorkflows).where(
                    UserWorkflows.user_id == user.user_id,
                    UserWorkflows.type_id == spec["type_id"],
                    UserWorkflows.name == spec["name"],
                    UserWorkflows.deleted == 0,
                )
            )
        ).scalar_one_or_none()
        if existing:
            print(f"[seed-demo] workflow exists (id={existing.workflow_id}): {spec['name']}")
            continue
        wf = UserWorkflows(
            user_id=user.user_id,
            group_id=user.group_id,
            type_id=spec["type_id"],
            name=spec["name"],
            config=spec["config"],
            enabled=True,
        )
        session.add(wf)
        n_created += 1
        await session.flush()
        print(f"[seed-demo] created workflow (id={wf.workflow_id}, type={spec['type_id']}): {spec['name']}")
    return n_created


async def run(args: argparse.Namespace) -> None:
    source_dir = Path(args.source_dir).expanduser().resolve()
    fs_root = Path(args.file_system_root).expanduser().resolve()

    if not source_dir.exists():
        print(f"[seed-demo] source dir does not exist: {source_dir}")
        print("[seed-demo]   create it and stage fixtures per the layout in this script's docstring.")
        sys.exit(2)

    async with SqlAsyncSession() as session:
        try:
            group = await _upsert_group(session, args.group_name)
            await _upsert_group_setting(session, group.group_id, "file_system_root", str(fs_root))
            user = await _upsert_user(
                session, group, args.demo_user_name, args.password,
                full_name=f"{args.demo_user_name.replace('_', ' ').title()} (demo)",
            )

            inputs_dir = fs_root / str(group.group_id) / str(user.user_id) / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            copied, skipped = _copy_fixtures(source_dir, inputs_dir)

            n_workflows = await _upsert_workflows(session, user, _workflow_specs())

            if args.dry_run:
                await session.rollback()
                print("[seed-demo] DRY RUN — rolled back DB changes")
                return

            await session.commit()
            print("[seed-demo] committed")
            print(f"[seed-demo] summary: group_id={group.group_id} user_id={user.user_id} "
                  f"fixtures(copied={copied}, skipped={skipped}) new_workflows={n_workflows}")
            print(f"[seed-demo] inputs dir: {inputs_dir}")
            print(f"[seed-demo] login: user={args.demo_user_name} email={user.email}")
        except Exception:
            await session.rollback()
            raise

    await sql_async_engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source-dir", default="~/p51_demo_fixtures",
                   help="Directory containing the staged fixture layout (default: %(default)s)")
    p.add_argument("--group-name", default="Demo",
                   help="ApiGroups.group_name to find or create (default: %(default)s)")
    p.add_argument("--demo-user-name", default="demo_user",
                   help="Slug used for user_name and email local-part (default: %(default)s)")
    p.add_argument("--password", default="demo-5555",
                   help="Initial password for the demo user (default: %(default)s)")
    p.add_argument("--file-system-root", default="~/p51_demo_group_area",
                   help="group_settings.file_system_root for the demo group (default: %(default)s)")
    p.add_argument("--dry-run", action="store_true",
                   help="Run all checks and prints, then roll back the DB transaction")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(_parse_args()))

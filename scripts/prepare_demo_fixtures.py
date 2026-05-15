"""Download upstream demo datasets and stage them in the layout
scripts/seed_demo.py consumes.

Each dataset has an idempotent prepare function: re-running this script
skips work whose output already exists. The download cache and the staged
output dir are separate so the cache survives a re-stage.

Upstream sources (all public, no auth):
- UCI Online Retail II → https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
- NYC 311 → Socrata API at data.cityofnewyork.us
- CUAD v1 contracts → Zenodo (https://zenodo.org/records/4595826)
- Enron emails → HuggingFace dataset `corbt/enron-emails`

Total raw download ≈ 270 MB; staged output ≈ 130 MB.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent

import pandas as pd  # noqa: E402


# ── Upstream URLs ──────────────────────────────────────────────────

UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

NYC_SOCRATA_CSV_URL = (
    "https://data.cityofnewyork.us/resource/erm2-nwe9.csv?"
    "$where=" + urllib.parse.quote(
        "borough='MANHATTAN' AND "
        "created_date between '2024-09-01T00:00:00' and '2024-12-31T23:59:59'"
    ) + "&$limit=400000"
)

CUAD_ZIP_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip"

ENRON_PARQUET_URL = (
    "https://huggingface.co/datasets/corbt/enron-emails/"
    "resolve/main/data/train-00000-of-00003.parquet"
)


# ── HTTP helpers ───────────────────────────────────────────────────


def _download_to(url: str, dst: Path, *, label: str | None = None) -> Path:
    """Download `url` to `dst` if it doesn't already exist. Returns dst."""
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  [cache] {dst.name} already present ({dst.stat().st_size:,} bytes)")
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [http] GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "p51-demo-fixtures/1.0"})
    with urllib.request.urlopen(req) as r, open(dst, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f, length=1 << 20)
    print(f"  [http] saved {dst} ({dst.stat().st_size:,} bytes)")
    return dst


# ── UCI Online Retail II ───────────────────────────────────────────


def prepare_uci(cache_dir: Path, output_dir: Path) -> None:
    print("[uci_online_retail] preparing")
    out = output_dir / "uci_online_retail"
    out.mkdir(parents=True, exist_ok=True)

    xlsx_out = out / "online_retail_II.xlsx"
    y1_csv = out / "online_retail_2009_2010.csv"
    y2_csv = out / "online_retail_2010_2011.csv"
    if all(p.exists() for p in (xlsx_out, y1_csv, y2_csv)):
        print("  all outputs present; skipping")
        return

    zip_path = _download_to(UCI_ZIP_URL, cache_dir / "online_retail_II.zip")
    with zipfile.ZipFile(zip_path) as zf:
        xlsx_member = next(m for m in zf.namelist() if m.lower().endswith(".xlsx"))
        with zf.open(xlsx_member) as src, open(xlsx_out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    print(f"  extracted {xlsx_out}")

    sheets = pd.read_excel(xlsx_out, sheet_name=None)
    sheet_to_path = {
        "Year 2009-2010": y1_csv,
        "Year 2010-2011": y2_csv,
    }
    for sheet_name, df in sheets.items():
        dst = sheet_to_path.get(sheet_name)
        if dst is None:
            print(f"  unknown sheet {sheet_name!r}; skipping")
            continue
        df.to_csv(dst, index=False)
        print(f"  wrote {dst} ({len(df):,} rows)")


# ── NYC 311 ────────────────────────────────────────────────────────


def prepare_nyc311(cache_dir: Path, output_dir: Path) -> None:
    print("[nyc311] preparing")
    out = output_dir / "nyc311"
    out.mkdir(parents=True, exist_ok=True)
    sample_path = out / "nyc311_manhattan_2024_sample.csv"
    if sample_path.exists():
        print("  sample present; skipping")
        return

    raw_path = _download_to(
        NYC_SOCRATA_CSV_URL,
        cache_dir / "nyc311_manhattan_2024_raw.csv",
    )
    df = pd.read_csv(raw_path, low_memory=False)
    # Deterministic order so the 25% slice is stable across reruns
    df = df.sort_values("unique_key").reset_index(drop=True)
    sample = df.iloc[::4]
    sample.to_csv(sample_path, index=False)
    print(f"  wrote {sample_path} ({len(sample):,} rows out of {len(df):,})")


# ── CUAD v1 contracts ──────────────────────────────────────────────


def prepare_cuad(cache_dir: Path, output_dir: Path) -> None:
    print("[cuad_contracts] preparing")
    out = output_dir / "cuad_contracts"
    out.mkdir(parents=True, exist_ok=True)
    mc_out = out / "master_clauses.csv"
    meta_out = out / "contracts_metadata.csv"
    if mc_out.exists() and meta_out.exists():
        print("  all outputs present; skipping")
        return

    zip_path = _download_to(CUAD_ZIP_URL, cache_dir / "CUAD_v1.zip")
    with zipfile.ZipFile(zip_path) as zf:
        # 1. master_clauses.csv — direct extract
        mc_member = next(m for m in zf.namelist() if m.endswith("master_clauses.csv"))
        with zf.open(mc_member) as src, open(mc_out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        print(f"  extracted {mc_out}")

        # 2. contracts_metadata.csv — derived from PDF directory tree.
        # Build {stem_lower: (part, category)} without extracting the PDFs.
        pdf_re = re.compile(
            r"^CUAD_v1/full_contract_pdf/(?P<part>[^/]+)/(?P<cat>[^/]+)/(?P<fn>[^/]+\.pdf)$",
            re.IGNORECASE,
        )
        stem_map: dict[str, tuple[str, str]] = {}
        for member in zf.namelist():
            m = pdf_re.match(member)
            if not m:
                continue
            fn = m.group("fn")
            stem = os.path.splitext(fn)[0].lower().strip()
            stem_map[stem] = (m.group("part"), m.group("cat"))
        print(f"  indexed {len(stem_map):,} CUAD PDFs")

    mc = pd.read_csv(mc_out, usecols=["Filename"])

    def lookup(fn: str) -> tuple[str | None, str | None]:
        s = os.path.splitext(str(fn).strip())[0].lower().strip()
        return stem_map.get(s, (None, None))

    mc[["part", "contract_category"]] = mc["Filename"].apply(
        lambda x: pd.Series(lookup(x))
    )

    # Fuzzy fallback for any non-matches: stem prefix match
    unmatched_mask = mc["part"].isna()
    if unmatched_mask.any():
        for idx, fn in mc.loc[unmatched_mask, "Filename"].items():
            prefix = os.path.splitext(str(fn).strip())[0].lower().strip()[:30]
            for stem, (part, cat) in stem_map.items():
                if stem.startswith(prefix):
                    mc.at[idx, "part"] = part
                    mc.at[idx, "contract_category"] = cat
                    break

    family_map = {
        "Affiliate Agreement": "Affiliate", "Agency Agreements": "Agency",
        "Collaboration": "Collaboration", "Consulting Agreements": "Consulting",
        "Co_Branding": "CoBranding", "Distributor": "Distribution",
        "Development": "Development", "Endorsement": "Endorsement",
        "Endorsement Agreement": "Endorsement", "Franchise": "Franchise",
        "Hosting": "Hosting", "IP": "IP", "Joint Venture _ Filing": "Joint Venture",
        "License Agreements": "License", "Maintenance": "Maintenance",
        "Manufacturing": "Manufacturing", "Marketing": "Marketing",
        "Outsourcing": "Outsourcing", "Promotion": "Promotion",
        "Reseller": "Reseller", "Service": "Service", "Services": "Service",
        "Sponsorship": "Sponsorship", "Strategic Alliance": "Strategic Alliance",
        "Supply": "Supply", "Transportation": "Transportation",
    }
    mc["family"] = mc["contract_category"].map(family_map).fillna(mc["contract_category"])
    mc["part"] = mc["part"].fillna("Unknown")
    mc["contract_category"] = mc["contract_category"].fillna("Unknown")
    mc["family"] = mc["family"].fillna("Unknown")
    mc[["Filename", "part", "contract_category", "family"]].to_csv(meta_out, index=False)
    print(f"  wrote {meta_out} ({len(mc):,} rows)")


# ── Enron emails ───────────────────────────────────────────────────


def prepare_enron(cache_dir: Path, output_dir: Path) -> None:
    print("[enron] preparing")
    out = output_dir / "enron"
    out.mkdir(parents=True, exist_ok=True)
    sample_path = out / "enron_emails_sample.csv"
    if sample_path.exists():
        print("  sample present; skipping")
        return

    pq_path = _download_to(
        ENRON_PARQUET_URL,
        cache_dir / "enron_train-00000-of-00003.parquet",
    )
    df = pd.read_parquet(
        pq_path,
        columns=["message_id", "subject", "from", "to", "cc", "date", "body", "file_name"],
    )
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    df = df.dropna(subset=["date_parsed"])
    df["year"] = df["date_parsed"].dt.year

    focus = df[df["year"].between(2000, 2001)].copy()
    focus["ym"] = focus["date_parsed"].dt.to_period("M").astype(str)
    n_months = focus["ym"].nunique()
    n_per = max(1, 5000 // max(n_months, 1))
    sample = (
        focus.groupby("ym", group_keys=False)
             .apply(lambda g: g.sample(n=min(len(g), n_per), random_state=42))
    )
    sample = sample.sort_values("date_parsed").reset_index(drop=True)

    def _clean(b: object) -> str:
        if not isinstance(b, str):
            return ""
        return re.sub(r"\s+", " ", b).strip()[:1000]

    sample["body_truncated"] = sample["body"].apply(_clean)
    out_cols = ["message_id", "date_parsed", "from", "to", "cc", "subject",
                "body_truncated", "file_name"]
    sample = sample[out_cols].rename(columns={"date_parsed": "date"})
    sample.to_csv(sample_path, index=False)
    print(f"  wrote {sample_path} ({len(sample):,} rows)")


# ── Driver ─────────────────────────────────────────────────────────


STEPS: list[tuple[str, Callable]] = [
    ("uci", prepare_uci),
    ("nyc311", prepare_nyc311),
    ("cuad", prepare_cuad),
    ("enron", prepare_enron),
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output-dir", default="~/p51_demo_fixtures",
                   help="Where to write the staged layout (default: %(default)s)")
    p.add_argument("--cache-dir", default="~/.cache/p51_demo_fixtures",
                   help="Where to keep raw downloads (default: %(default)s)")
    p.add_argument("--only", action="append", choices=[s for s, _ in STEPS],
                   help="Run only these step(s); repeatable.")
    args = p.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"[prepare-demo-fixtures] output_dir={output_dir}")
    print(f"[prepare-demo-fixtures] cache_dir={cache_dir}")

    steps = [(name, fn) for name, fn in STEPS if not args.only or name in args.only]
    for name, fn in steps:
        fn(cache_dir, output_dir)

    print("[prepare-demo-fixtures] done")
    print(f"  next: ./venv/bin/python scripts/seed_demo.py --source-dir {output_dir}")


if __name__ == "__main__":
    main()

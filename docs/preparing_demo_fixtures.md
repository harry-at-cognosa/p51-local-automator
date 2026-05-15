# Preparing the demo fixtures bundle

This is a **maintainer** doc. Customers install the demo by running
`scripts/seed_demo.py` against a fixtures bundle the maintainer
provides — they don't need to fetch anything from upstream.

Use `scripts/prepare_demo_fixtures.py` when you need to:
- Build the fixtures bundle for the first time on a new dev machine
- Refresh the bundle when an upstream source has changed in a way the
  demo relies on (rare — these are stable academic datasets)
- Diagnose a "the bundle doesn't match what the workflows expect" issue

## Sources

All four upstream sources are public, no auth required:

| Dataset | Upstream | License | Raw size |
|---|---|---|---|
| UCI Online Retail II | https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip | CC BY 4.0 | ~45 MB zip |
| NYC 311 Manhattan 2024 | Socrata API at `data.cityofnewyork.us/resource/erm2-nwe9.csv` | NYC Open Data Terms | ~140 MB CSV |
| CUAD v1 contracts | https://zenodo.org/records/4595826/files/CUAD_v1.zip | CC BY 4.0 | ~159 MB zip |
| Enron emails | HuggingFace `corbt/enron-emails`, parquet shard 0 of 3 | Public domain (federal investigation) | ~25 MB parquet |

Total raw download is ~370 MB; staged output is ~130 MB on disk.

## Run

```bash
./venv/bin/python scripts/prepare_demo_fixtures.py \
    --output-dir ~/p51_demo_fixtures \
    --cache-dir  ~/.cache/p51_demo_fixtures
```

Flags:
- `--output-dir` — where to write the staged layout. This is what
  `seed_demo.py --source-dir` consumes.
- `--cache-dir` — where to keep raw downloads. Survives a re-stage so
  reruns are fast.
- `--only uci|nyc311|cuad|enron` — run a single step. Repeatable.

The script is idempotent: each step skips if its outputs are already
present in `--output-dir`. To force a refresh of one step, delete that
step's subdir under `--output-dir` and re-run.

## What each step does

### `uci_online_retail`

1. Downloads the UCI zip if not cached.
2. Extracts `online_retail_II.xlsx` to the output dir.
3. Reads both sheets ("Year 2009-2010", "Year 2010-2011"), writes each
   to a per-year CSV (`online_retail_2009_2010.csv`,
   `online_retail_2010_2011.csv`).

The xlsx is kept alongside the CSVs because the Type 2 demo workflow
points at the xlsx directly (with `analyze_data.py` concatenating both
sheets), while the Type 7 demo workflow points at the two CSVs as a
multi-table input.

### `nyc311`

1. Hits the Socrata API for `borough=MANHATTAN AND created_date BETWEEN
   2024-09-01 AND 2024-12-31`, with `$limit=400000` to safely cover the
   ~200k actual rows.
2. Sorts by `unique_key` for determinism (Socrata doesn't guarantee
   ordering across requests).
3. Takes a 25% systematic slice (every 4th row) → ~50k rows.

If NYC adds or backfills records for that period, the row count and
sample composition will shift. The demo's analysis goal is robust to
this — it asks about complaint-type distribution and trend, not exact
counts.

### `cuad_contracts`

1. Downloads the CUAD v1 zip from Zenodo if not cached.
2. Extracts `master_clauses.csv` directly from the zip — no full
   extract needed.
3. Walks the `full_contract_pdf/` member list inside the zip to build
   `{stem_lower: (part, contract_category)}`.
4. Joins each `master_clauses.csv` row to that index by case-folded
   filename stem (501/510 match exactly; the rest fall through to a
   30-char-prefix fuzzy match — 505/510 total; the 5 remaining are
   labeled `Unknown`).
5. Adds a coarse `family` column (e.g. `Distributor` and `Distribution`
   both collapse to `Distribution`).
6. Writes `contracts_metadata.csv` (Filename, part, contract_category,
   family).

The PDFs themselves are never extracted — only the directory tree
inside the zip is consulted, which saves ~270 MB of disk.

### `enron`

1. Downloads shard 0 of 3 (the cleaned `corbt/enron-emails` parquet
   from HuggingFace) if not cached. One shard has ~170k messages —
   plenty for a 5k-row sample.
2. Parses the `date` field with UTC awareness, drops un-parseable rows.
3. Filters to 2000–2001 (the years where this employee had real Enron
   email activity).
4. Stratifies the sample by year-month so the resulting CSV covers the
   full date span evenly.
5. Collapses internal whitespace in each body and truncates to 1,000
   characters — keeps the CSV manageable while preserving topic signal.
6. Writes `enron_emails_sample.csv` (~5k rows).

`random_state=42` is fixed so the sample is reproducible across reruns.

## After running

The output layout matches what `seed_demo.py` expects:

```
~/p51_demo_fixtures/
├── cuad_contracts/
│   ├── contracts_metadata.csv
│   └── master_clauses.csv
├── enron/
│   └── enron_emails_sample.csv
├── nyc311/
│   └── nyc311_manhattan_2024_sample.csv
└── uci_online_retail/
    ├── online_retail_2009_2010.csv
    ├── online_retail_2010_2011.csv
    └── online_retail_II.xlsx
```

You can now bundle this directory (zip / tar.gz) and distribute it to
customer installs.

## Distributing the bundle

A simple tarball works:

```bash
tar -czf p51_demo_fixtures.tar.gz -C ~/p51_demo_fixtures .
```

Customer install side:

```bash
mkdir -p ~/p51_demo_fixtures
tar -xzf p51_demo_fixtures.tar.gz -C ~/p51_demo_fixtures
./venv/bin/python scripts/seed_demo.py --source-dir ~/p51_demo_fixtures
```

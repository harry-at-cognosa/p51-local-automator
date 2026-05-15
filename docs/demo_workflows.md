# Demo workflows

The platform ships with five sample workflows you can run within a minute
of finishing the install. They cover both workflow types that take
external tabular data — Type 2 (Transaction Data Analyzer) and Type 7
(Analyze Data Collection) — and they exercise four canonical public
datasets so the reports look like real work, not toy output.

The goal of the demo set is **"can I see this thing actually do
something useful in five minutes?"** rather than benchmark coverage. A
new admin should be able to log in as `demo_user`, click into any one of
these workflows, hit *Run*, and get a real artifact back.

## Prerequisites

1. The platform is installed and `alembic upgrade head` has been run.
2. The fixtures bundle is present at a path you can name (default
   `~/p51_demo_fixtures`). The bundle is provided separately — see
   [preparing_demo_fixtures.md](preparing_demo_fixtures.md) if you need
   to regenerate it from upstream sources. It's ~130 MB unpacked.
3. `ANTHROPIC_API_KEY` is set in `.env` (Type 2 makes one LLM call;
   Type 7 makes ~20–40 across six stages).

## Install

```bash
./venv/bin/python scripts/seed_demo.py --source-dir ~/p51_demo_fixtures
```

Optional flags:
- `--group-name Demo` (default) — name of the group it creates
- `--demo-user-name demo_user` (default) — login slug
- `--password demo-5555` (default) — initial password
- `--file-system-root ~/p51_demo_group_area` (default) — where workflow
  artifacts and the inputs sandbox live for this group
- `--dry-run` — preview everything, roll back the DB transaction

The script is idempotent: rerunning is safe and never overwrites an
existing workflow row (so if you've tuned a demo workflow's config in
the UI, your edits survive).

What it creates on a fresh install:
- One `Demo` group with `file_system_root` set
- One `demo_user` with the password above (manager role, not superuser)
- Seven fixture files copied into the user's inputs sandbox
- Five workflows wired to those fixtures

Log in at `http://localhost:8000/app` as `demo_user` /
`demo-5555` and the workflows appear on the Workflows page.

## The five workflows

Each row below corresponds to one entry on the Workflows page. Runtimes
and token figures are from real runs on a Mac Mini against
`claude-opus-4-7` (your mileage will vary by a small factor).

### 1. UCI Online Retail II — UK e-commerce transactions (Type 2)

- **Input:** `uci_online_retail/online_retail_II.xlsx` — 1,067,371
  transactions, two sheets concatenated, Dec 2009 → Dec 2011, single UK
  online retailer
- **What it does:** profiles the data, filters to the requested date
  range (none by default), picks key fields, computes per-column
  statistics, renders a monthly trend chart, then asks the LLM to write
  a narrative summary
- **Expected runtime:** ~60 s
- **LLM cost:** ~1.3k tokens
- **Artifacts:** profile (md), filtered data (csv — falls back from
  xlsx automatically when row count exceeds Excel's cap), monthly trend
  chart (png), summary report (md), quality report (md), LLM narrative
  (json)
- **What "good" looks like:** the summary report shows total
  revenue, mean / median / max prices, a Dec 2009 → Dec 2011 trend, and
  the narrative json describes the seasonal pattern (UK retail spikes
  in Nov–Dec, dips Jan–Feb) and flags negative-quantity rows as returns

### 2. NYC 311 Manhattan 2024 — Sep–Dec service requests (Type 2)

- **Input:** `nyc311/nyc311_manhattan_2024_sample.csv` — 50,000 311
  service requests sampled from Manhattan, Sep–Dec 2024 (the original
  query returns ~200k; this is a 25% systematic slice for demo speed)
- **What it does:** same Type 2 pipeline against richly categorical
  public-sector data
- **Expected runtime:** ~25 s
- **LLM cost:** ~4.3k tokens
- **Artifacts:** profile, filtered xlsx, two charts (by_category and
  trend), summary, quality, narrative json
- **What "good" looks like:** category chart shows top complaint
  types (Noise — Residential, Illegal Parking, Heat/Hot Water are
  typical leaders); trend chart shows Sep was light (data starts
  mid-month), Oct/Nov/Dec are roughly even; narrative flags any agency
  that handles a disproportionate share

### 3. Enron emails 2000–2001 — sender/topic patterns (Type 2)

- **Input:** `enron/enron_emails_sample.csv` — 4,992 messages
  stratified across 2000–2001 (one slice from the cleaned HuggingFace
  `corbt/enron-emails` dataset), bodies truncated to 1,000 chars
- **What it does:** profiles a non-numeric, text-heavy dataset; the LLM
  narrative is where most of the value lives here, since the structural
  stats only describe time/sender distribution
- **Expected runtime:** ~10 s
- **LLM cost:** ~1.0k tokens
- **Artifacts:** profile, filtered xlsx, summary, quality, narrative
- **What "good" looks like:** profile shows ~5k rows, columns include
  from/to/subject/body_truncated; narrative typically points out the
  message-volume spike around late 2001 (the collapse) and notes the
  high concentration of senders in a small group

### 4. CUAD contracts — clause variance by category (Type 7)

- **Inputs (two-table):**
  - `cuad_contracts/master_clauses.csv` — 510 commercial contracts × 80
    columns (40 clause categories × 2 cols each: text + Yes/No)
  - `cuad_contracts/contracts_metadata.csv` — 510 rows derived from
    CUAD's PDF directory tree: Filename, part, contract_category, family
- **What it does:** the AWF-1 agentic engine runs through six stages
  (ingest → profile → analyze → synthesize → audit → scribe) and
  produces a multi-section report on how clause patterns (Cap on
  Liability, Governing Law, Non-Compete, etc.) vary across contract
  categories
- **Expected runtime:** 3–4 minutes
- **LLM cost:** ~150k cached + ~31k input/output tokens (~$0.50 list
  with caching)
- **Artifacts:** `draft_report.md`, `audit_critique.json`,
  `cuad_clause_variance_by_category_YYMMDD_FinalReport.md`
- **What "good" looks like:** Final report has 5 sections per the
  workflow's `report_structure`; the corpus overview names actual top
  categories (Distributor, Sponsorship, Strategic Alliance,
  Maintenance, License); the clause-presence matrix gives percentages
  per category; the methodological caveats section lists any clauses
  that aren't present in the data
- **Known agent shortcut:** the agent often derives the category from
  the trailing token of `Filename` (e.g. `..._Sponsorship Agreement.pdf`)
  instead of joining to `contracts_metadata.csv`. The output is still
  correct — it's just a more direct path the model finds on its own.

### 5. UCI Online Retail — year-over-year 2009-10 vs 2010-11 (Type 7)

- **Inputs (two-table):**
  - `uci_online_retail/online_retail_2009_2010.csv` (525k rows)
  - `uci_online_retail/online_retail_2010_2011.csv` (542k rows)
- **What it does:** Type 7 AWF-1 over the same UCI data split by fiscal
  year — quantifies YoY change in revenue, orders, AOV, returns,
  customer count, country mix, and surfaces the months where the YoY
  delta is sharply non-uniform
- **Expected runtime:** ~4 minutes
- **LLM cost:** ~470k input + ~11k output tokens (~$0.50 list)
- **Artifacts:** `draft_report.md`, `audit_critique.json`, two country
  bar charts (`t1_country_qty.png`, `t2_country_qty.png`),
  `uci_retail_yoy_2010_vs_2011_YYMMDD_FinalReport.md`
- **What "good" looks like:** headline YoY table shows revenue,
  orders, AOV, returns, customer count; country mix shows UK
  dominance (~85%+) with EIRE, Germany, France, Netherlands among the
  top 5; one-decimal-precision percentages throughout; the inflection
  point section calls out any month with an unusually large YoY swing

## Where outputs go

Every run lands under
`<file_system_root>/{group_id}/{user_id}/{workflow_id}/{run_id}/`. For
the default demo install that's
`~/p51_demo_group_area/<group_id>/<user_id>/<workflow_id>/<run_id>/`.

From the UI, the **Runs** page on each workflow lists every run with a
link to view artifacts.

## Troubleshooting

**The seed script reports `MISSING source fixture: ...`.** The fixtures
bundle isn't where `--source-dir` points. Stage the bundle and re-run;
existing rows are left alone, only the missing copies are made.

**A workflow run fails immediately with "Data file not found".** The
fixture wasn't copied — same root cause as above, but the workflow row
already existed when you re-staged. Re-run `seed_demo.py` to refresh the
file copies (DB rows are untouched).

**Type 7 (CUAD or YoY) times out partway through.** The default stage
timeout is 10 min per stage. On a slow Mac Mini you can bump it via the
workflow's `stage_timeout_seconds` config field, or set the group-level
`stage_timeout_seconds` setting in `group_settings`.

**`ANTHROPIC_API_KEY` rate limits.** Both Type 7 runs make 100+ LLM
calls each. If you trigger both back-to-back you may hit a TPM cap on
some accounts; wait a minute or stagger them.

## What's deliberately not in the demo

- **Email-monitor / calendar / auto-reply workflows (Types 1, 3, 5,
  6).** Those need real Gmail/Apple-Mail/Calendar accounts. The demo
  set is for showing the platform's value without needing to wire up
  external accounts.
- **SQL Query Runner (Type 4).** No demo dataset for this yet.
- **Raw-document Type 7.** The current Type 7 engine ingests CSV/XLSX
  only. PDFs and emails in the bundle (CUAD raw contracts, Enron raw
  parquet) have been transformed to tabular form; a future engine
  release will accept raw documents directly.

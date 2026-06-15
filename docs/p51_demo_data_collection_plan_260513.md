# p51 demo data collection plan — Type 2 and Type 7 workflows

**Created:** 2026-05-13

## Context

Need concrete demo data to exercise the Type 2 ("Transaction Data Analyzer") and Type 7 ("Analyze Data Collection" / AWF-1) workflows in p51. No private/business data to use, so this leans on well-known public datasets with stable URLs, named slugs (Kaggle, HuggingFace, UCI), and clear retrieval instructions — the LLM-benchmark-style canon — not generic pointers to data.gov.

This file is the catalog. Once we've chosen, we download 3–4 and stand them up as ready-made demo fixtures under `<file_system_root>/{group_id}/{user_id}/inputs/`.

Everything below is public and free. Kaggle requires a free account + API token; UCI, HuggingFace, NYC Open Data, and arXiv do not.

---

## Type 2 — Transaction Data Analyzer datasets

Best fit: one tabular file, date column, amount or count column, at least one categorical dimension, 6+ months of history. CSV preferred (Excel acceptable).

### Top picks (start here)

1. UCI Online Retail II — UK e-commerce
   - URL: https://archive.ics.uci.edu/dataset/502/online+retail+ii
   - Kaggle mirror: `mashlyn/online-retail-ii-uci`
   - Format: .xlsx (one sheet per year) — easy to convert to CSV
   - Size: 22 MB, 541k transaction rows
   - Schema: InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country
   - Date range: Dec 2009 – Sep 2011 (21 months)
   - Why pick first: realistic e-commerce structure, manageable size, no joins needed, multiple categorical dims (country, product), and negative quantities (returns) give the LLM something interesting to flag.

2. Olist Brazilian e-commerce
   - Kaggle slug: `olistbr/brazilian-ecommerce`
   - URL: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
   - Format: 8 CSVs, ~100–200 MB unzipped
   - Rows: 99k orders, 112k order items
   - Date range: Jan 2016 – Oct 2018 (34 months)
   - Schema highlights: order_id, order_date, payment_type, payment_installments, product_category (with EN translation file), order_status (7 states), customer state
   - Caveat: needs join of orders + order_items + products to get product-level rows. Good if you want the demo to show multi-file ingest.

3. NYC 311 service requests
   - Official source: https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9
   - Direct CSV export from "Export" button — no account required
   - Full size: multi-GB; use the Socrata API with filters to slice
   - Schema: unique_key, created_date, closed_date, agency, complaint_type, descriptor, borough, status, latitude, longitude
   - Categorical richness: 200+ complaint_types, 30+ agencies, 5 boroughs
   - Starter slice: query string `?$where=borough='MANHATTAN' AND created_date between '2024-01-01T00:00:00' and '2024-12-31T00:00:00'&$limit=100000` → about 50–100 MB. Lets you ask "what changed Q3→Q4?" without choking on size.

### Other strong candidates

4. Chicago crime incidents
   - Kaggle slug: `chicago/chicago-crime` — https://www.kaggle.com/datasets/chicago/chicago-crime
   - Also Chicago Data Portal: https://data.cityofchicago.org/Public-Safety/Crimes-2001-to-Present/ijzp-q8t2
   - Schema: case_number, date, primary_type (40+ crime categories), description, location_description, arrest (bool), domestic (bool), beat, district, ward, lat/lon
   - Date range: 2001 → present (20+ years)
   - Starter slice: filter to 2023 only, ~250k rows, ~80 MB.

5. NYC Yellow Taxi trips (with caveat)
   - Official: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
   - AWS open data: https://registry.opendata.aws/nyc-tlc-trip-records-pds/
   - Format: Parquet, monthly files ~50–100 MB each — NOT CSV. Would need pandas/pyarrow conversion before Type 2 can ingest it. If we don't want that friction, skip.
   - Kaggle CSV mirror (older, smaller): `elemento/nyc-yellow-taxi-trip-data`
   - One month of trips is plenty for a demo.

6. Credit card fraud detection
   - Kaggle slug: `mlg-ulb/creditcardfraud` — https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
   - 144 MB, 284k transactions, Class column (fraud=1)
   - Caveat: only 2 days of data (Sept 2013) and V1–V28 are anonymized PCA features. Good for "fraud rate by hour, by amount bucket" but no months-over-months story.

7. DonorsChoose donations
   - Kaggle competition: https://www.kaggle.com/c/donorschoose-application-screening/data
   - Multi-file: projects, donations, resources, essays
   - Categorical richness: subject (math/science/literacy/...), grade level (K–12), donor state, resource type
   - 1M+ donations across multiple years — slice by year. Useful for a nonprofit-flavored demo.

8. Instacart market basket
   - Kaggle: https://www.kaggle.com/c/instacart-market-basket-analysis/data
   - 3M+ orders, ~500 MB
   - Heavy caveat: NO absolute dates — only day-of-week and hour. Cannot do month-over-month trend; only diurnal/weekly patterns. Probably skip unless we specifically want a "basket analytics" demo.

9. Supermarket sales (Malaysia)
   - Kaggle slug: `aungpyaeap/supermarket-sales`
   - Tiny: 1,000 rows, 5 MB, Jan–Mar 2019 only
   - Schema: branch (3 locations), city, customer_type (member/non-member), gender, product_line (6 categories), unit_price, quantity, payment, gross_income, rating
   - Why include: smallest, fastest demo. 30-second download, runs in milliseconds. Good for "first time seeing the tool work."

10. UCI Bank Marketing / Adult / German Credit — the classic UCI tabular trio
    - Bank Marketing: https://archive.ics.uci.edu/dataset/222/bank+marketing — 45k rows of marketing call outcomes with customer attributes
    - Adult (Census Income): https://archive.ics.uci.edu/dataset/2/adult — not transactional but a classic categorical-rich tabular file
    - These are the "MNIST of tabular data." Useful as a fallback if Online Retail II doesn't land — every ML tutorial uses them, so the LLM has seen them in training.

### Type 2 download cheat-sheet

Kaggle (one-time setup):
- Account → Settings → API → "Create New API Token" → save as `~/.kaggle/kaggle.json`, chmod 600
- `pip install kaggle`
- `kaggle datasets download -d olistbr/brazilian-ecommerce` (then unzip)
- For competition data: `kaggle competitions download -c instacart-market-basket-analysis` (must accept terms once on the web)

UCI: click "Download" on the dataset page — no account, gives you a zip with .data and .names files (the .names file is the schema doc).

NYC Open Data: each dataset page has an "Export → CSV" button. For programmatic access use the SODA API, e.g.
`https://data.cityofnewyork.us/resource/erm2-nwe9.csv?$where=...&$limit=100000`

---

## Type 7 — Analyze Data Collection datasets

Best fit: 20–200 documents, mixed formats (PDF/EML/DOCX/MD/TXT), value is in cross-document synthesis. Below are the canonical / LLM-benchmark-style corpora.

### Top picks (start here)

1. CUAD — Contract Understanding Atticus Dataset
   - Official: https://www.atticusprojectai.org/cuad
   - HuggingFace: `theatticusproject/cuad`
   - Zenodo (raw archive): https://zenodo.org/records/4595826
   - Content: 510 real commercial contracts as PDF + TXT, plus 13,000 expert-labeled clauses across 41 categories
   - Size: 159 MB total
   - License: CC-BY-4.0 — commercial use OK
   - Starter slice: first 30 contracts. Demo question: "Across these 30 SaaS agreements, summarize the variance in auto-renewal, indemnity caps, and termination-for-convenience clauses." Perfect Type 7 fit.

2. Enron email corpus
   - HuggingFace (cleaned): `corbt/enron-emails` (Parquet, structured fields)
   - Kaggle: `wcukierski/enron-email-dataset` (raw maildir tree)
   - CMU original: https://www.cs.cmu.edu/~enron/
   - 517k messages from ~150 senior Enron employees
   - Starter slice: one person's sent folder (~2k messages). Demo question: "Trace this person's involvement in the Valhalla trades — what did they know and when?"

3. SEC EDGAR 10-K filings
   - HuggingFace `jlohding/sp500-edgar-10k` — 6,282 10-Ks from S&P 500 constituents 2010–2022, already split into Item 1, Item 1A, Item 7, etc. Parquet, ~964 MB.
   - HuggingFace `eloukas/edgar-corpus` — broader cleaned EDGAR corpus
   - Raw EDGAR: https://www.sec.gov/edgar/searchedgar/companysearch
   - Starter slice: 10 tech-sector 10-Ks from 2020. Demo question: "Compare risk factors and pandemic-related language across these 10 filings — which were prescient, which were boilerplate?"

### Practical / mixed-format corpora

4. Yelp Open Dataset
   - Official: https://business.yelp.com/data/resources/open-dataset/ (registration required)
   - Kaggle: `yelp-dataset/yelp-dataset`
   - 6.9M reviews, 150k businesses, 11 metros
   - Format: 5 JSONL files (businesses, reviews, users, checkins, photos metadata) — 4 GB compressed
   - Starter slice: one city + one business category (e.g., all Phoenix restaurants, ~5k businesses, ~50k reviews). Demo question: "What are the top 3 recurring complaints across reviews of this restaurant in 2023? Did anything change vs 2022?"

5. Customer support tickets (multilingual, synthetic)
   - Kaggle: `tobiasbueck/multilingual-customer-support-tickets`
   - Several versions; v3 is 4k tickets across 10 languages, v5 is 20k EN/DE
   - Synthetic but realistic — queue routing, priority, type labels
   - Demo question: "Of these 200 tickets, group by root cause and identify the top 5 themes; which would benefit most from a new FAQ entry?"

6. arXiv papers by topic
   - API basics: https://info.arxiv.org/help/api/basics.html
   - Python wrapper: `pip install arxiv`
   - Bulk via AWS S3: https://info.arxiv.org/help/bulk_data.html
   - Rate limit: 1 request per 3 seconds; use `export.arxiv.org` for bulk
   - Starter slice: 50 PDFs tagged `cs.CL` from the last 12 months on a chosen topic. Demo question: "What are the 5 most common architectures, datasets, and limitations cited in these papers?"

### Multi-doc QA benchmarks (use these if we want ground-truth eval, not just vibes)

These were *built* for multi-document reasoning evaluation. Each comes with questions + answers + which paragraphs the answer requires — meaning we can score the workflow objectively, not just demo it.

7. HotpotQA
   - Site: https://hotpotqa.github.io
   - HuggingFace: `hotpotqa/hotpot_qa`
   - 113k Wikipedia-based questions, each answerable only by combining 2 articles
   - Has "bridge" vs "comparison" question types, easy/medium/hard difficulty, sentence-level supporting-fact annotations
   - License: CC-BY-SA-4.0
   - Use case: turn the workflow into an evaluable system. If we ever build a Type 7 eval harness, this is the data.

8. MuSiQue
   - GitHub: https://github.com/StonyBrookNLP/musique
   - Paper: https://aclanthology.org/2022.tacl-1.31/
   - 25k–50k 2–4-hop questions, designed to be unanswerable by single-hop shortcuts
   - Smaller and harder than HotpotQA; better stress test for an agentic loop.

### Domain-specific (more ambitious / larger)

9. CourtListener legal opinions
   - API: https://www.courtlistener.com/help/api/
   - Free token after registration
   - Endpoint examples: `/api/rest/v3/opinions/` for opinion text, `/api/rest/v3/clusters/` for case clusters
   - Starter slice: 50 Supreme Court opinions on a single topic (e.g., 4th Amendment search-and-seizure 2015–2020). Demo question: "Trace how the majority's reasoning evolved across these decisions."

10. PMC Open Access biomedical articles
    - FTP service: https://pmc.ncbi.nlm.nih.gov/tools/ftp/
    - AWS S3 registry: https://registry.opendata.aws/ncbi-pmc/
    - HuggingFace: `ncbi/pubmed` (PubMed abstracts)
    - 3.3M full-text articles available
    - Starter slice: 30 papers on a narrow topic via PMC full-text query. Demo question: "What treatments for [condition] have been studied; what were the reported outcomes?"

### Type 7 download cheat-sheet

HuggingFace:
- `pip install datasets`
- `from datasets import load_dataset; ds = load_dataset("theatticusproject/cuad")`
- For raw files (PDFs in CUAD), get them from the Zenodo archive instead — the HF dataset is the SQuAD-format Q&A, not the source PDFs.

CUAD raw PDFs: from Zenodo (https://zenodo.org/records/4595826), download `CUAD_v1.zip` → contains `CUAD_v1/full_contract_pdf/` with 510 PDFs organized by industry.

Enron: HuggingFace gives you clean Parquet (`corbt/enron-emails`); CMU original (`enron_mail_20150507.tar.gz`, ~423 MB) gives you the maildir tree if we want raw .eml-style files for ingest realism.

arXiv: `pip install arxiv`, then a few lines pull metadata + PDFs for a query.

CourtListener: register, get token, use REST API with `Authorization: Token <yours>`.

---

## Recommended first-download set

If we want to stand up one Type 2 demo and one Type 7 demo tomorrow with minimum friction:

- Type 2 primary: UCI Online Retail II (22 MB, no account, 21 months of multi-country retail).
- Type 2 secondary: NYC 311 Manhattan 2024 slice (~80 MB via Socrata, no account, real city data narrative).
- Type 7 primary: CUAD via Zenodo (510 PDFs, CC-BY, perfect demo question fit).
- Type 7 secondary: Enron sent-folder slice from HuggingFace (~2k messages, the canonical email corpus).

These four cover the most useful demo angles: e-commerce, public-sector, contracts, communications.

## Open questions for tomorrow

- Which two (or three) do we actually want me to pull down and place under a demo user's `inputs/` folder?
- Do we want a small wrapper script that creates a "demo_user" with these fixtures pre-loaded, so a new install can showcase Type 2 and Type 7 immediately?
- For Type 7, do we want a multi-doc QA benchmark (HotpotQA/MuSiQue) wired in as the basis for a future evaluation harness — or is that out of scope until we have a working demo?

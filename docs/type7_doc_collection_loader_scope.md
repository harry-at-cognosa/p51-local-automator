# Scope — Type 7 raw-document loader

**Status:** scope-only, awaiting go/no-go. No code in this proposal.

## Problem

Type 7 ("Analyze Data Collection" / AWF-1) is positioned in the product
narrative as "analyze a collection of 20–200 mixed-format documents."
The current engine actually only ingests CSV and XLSX —
`config_schema.filter_extensions = ["csv", "xlsx"]` and
`agentic_engine.stage_ingest` raises on anything else.

This forces the demo set into a transform-to-tabular detour: CUAD's
510 PDFs were collapsed into `master_clauses.csv`, Enron's parquet
shard was sampled and serialized to CSV. Each detour costs information
(the CUAD PDFs contain full clause text; the Enron CSV truncated bodies
to 1,000 chars).

A real customer dropping a folder of contracts or vendor emails into
their inputs sandbox and expecting Type 7 to "make sense of it" would
hit the same wall.

## Proposed change

Add a third ingest path alongside CSV/XLSX: a **document corpus**
ingest that loads a directory (or glob) of text-bearing files into the
agentic engine's working context, with the LLM seeing each document as
a named item with text content plus a small metadata header.

Three surface areas change:

### 1. Config schema (workflow_types.config_schema)

Add a new repeating-rows shape allowing a single Type 7 workflow to mix
tabular inputs and document-corpus inputs. A `kind` discriminator on
each row tells the engine which loader to use.

```jsonc
{
  "name": "data_definition",
  "type": "repeating_rows",
  "row_schema": [
    { "name": "kind", "type": "select",
      "options": [
        {"value": "table",  "label": "Tabular file (CSV/XLSX)"},
        {"value": "corpus", "label": "Document collection (folder)"}
      ],
      "default": "table" },
    { "name": "file", "type": "file_picker",
      "filter_extensions": ["csv", "xlsx"],
      "show_when": "kind == 'table'" },
    { "name": "folder", "type": "folder_picker",
      "show_when": "kind == 'corpus'" },
    { "name": "extensions", "type": "string_list",
      "default": ["txt", "md", "pdf", "eml"],
      "show_when": "kind == 'corpus'" },
    { "name": "description", "type": "multiline" }
  ]
}
```

Backwards-compatible: existing workflows with bare `file` rows default
`kind=table` and behave unchanged.

### 2. New skill: `load_corpus`

```python
@skill("load_corpus")
async def load_corpus(
    ctx, *,
    corpus_name: str,
    folder_path: str,
    extensions: list[str],
    max_files: int = 200,
    max_chars_per_file: int = 8000,
) -> dict:
    """Walk folder_path, read each file matching extensions, register
    in ctx.corpora[corpus_name] as a list of {name, text, metadata}.

    PDFs use pdfplumber (text extraction only — no OCR). EML files
    parse via stdlib email module: From, To, Subject, Date, body.
    .txt and .md read as-is. Other extensions raise.
    """
```

Returns a structural summary the engine can advertise to the LLM:
file count, total chars, top-level metadata fields available.

### 3. Engine ingest branch + downstream stages

`agentic_engine.stage_ingest` adds a third branch:

```python
if row.get("kind") == "corpus":
    await self._call_skill("load_corpus", corpus_name=...,
                           folder_path=..., extensions=...)
elif ext in ("csv",):
    await self._call_skill("load_csv", ...)
elif ext in ("xlsx", "xls"):
    await self._call_skill("load_xlsx", ...)
```

`stage_profile` learns to describe a corpus (file count, extension
mix, per-file char distribution, sample doc titles) the same way it
describes a DataFrame. `stage_analyze` exposes a `corpus_search` skill
(naive substring match plus optional embedding-based retrieval — out
of scope for v1) so the LLM can pull relevant doc passages without
seeing every file.

## Estimated effort

| Piece | Lines (rough) | Risk |
|---|---|---|
| `load_corpus` skill + PDF/EML readers | ~150 | Low — well-trodden ground |
| Engine ingest branch | ~30 | Low |
| Stage_profile corpus path | ~60 | Low |
| `corpus_search` skill (substring v1) | ~80 | Low |
| `config_schema` migration | ~20 | Low — additive |
| Frontend folder_picker + show_when wiring | ~120 | Medium — new picker component |
| Backwards-compat for existing Type 7 configs | ~10 | Low |
| Smoke test against CUAD raw PDFs + Enron .eml | — | Medium-high — first real test of the path |
| **Total backend** | ~360 | |
| **Total frontend** | ~120 | |

One phase, ~2–3 sessions of work for the engineer driving it. Could be
sequenced as:
1. Backend skill + ingest + profile (no UI yet, configurable via SQL)
2. Demo: load CUAD raw PDFs into a Type 7 workflow, verify
3. Frontend folder picker + show_when
4. Embedding-based corpus_search (separate phase if v1 substring search
   feels weak)

## Open questions for go/no-go

1. **PDF reader choice.** `pdfplumber` (pure-Python, no system deps,
   ~1 MB) vs `PyMuPDF` (faster, better text fidelity, ~25 MB native
   binary). Recommend pdfplumber for v1 — install simplicity matters
   on Mac Mini.
2. **`max_chars_per_file` budget.** 8k per doc × 200 docs = 1.6M
   chars. That comfortably fits in `claude-opus-4-7`'s 1M context only
   if the engine plays games with caching/retrieval. Recommend
   lazy-loading: the corpus index lists doc names + first 500 chars;
   full text loads only when the LLM calls `corpus_search`.
3. **`corpus_search` v1 ranking.** Substring frequency is dumb but
   honest. BM25 (no embedding dep) is a 1-day add. Embedding-based
   retrieval (sentence-transformers, ~150 MB model) is a separate
   phase. Recommend BM25 for v1.
4. **EML handling.** Real .eml files have multipart MIME, attachments,
   nested replies. v1 reads the plain-text body and ignores everything
   else (matches the Enron CSV's truncation philosophy). Acceptable?

## What this does NOT do

- OCR. Scanned-PDF contracts get partial text or nothing. v2 concern.
- Image extraction from PDFs. Same.
- Cross-document entity resolution (linking "Acme Inc." across docs).
  The LLM does this implicitly via context; no infra needed.
- Audio / video. Out of product scope.

## Recommendation

Worth doing — it's the largest single gap between "what the product
is" and "what the product currently does." Estimated 2–3 sessions.

Sequencing suggestion: ship the demo install + docs work first (this
PR), then start the loader phase as a separate planning effort. Don't
bundle.

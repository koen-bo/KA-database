# App Functionality and Gameplay Loop

## Functional Overview (Current State)
The app operates as a document intelligence workflow with automated ingestion, deterministic screening preparation, backend-controlled LLM screening, and operator inspection tools:
- Automated ingestion: sources are discovered via `rss`, `sitemap`, and `listing` methods, entries are filtered by tiered relevance rules, content is fetched/extracted, and new documents are stored in SQLite.
- Deterministic screening preparation: stored source text can be cleaned/backfilled into `cleaned_text`, excerpted with rule-based logic, and converted into a compact LLM request shape.
- Backend LLM screening: eligible documents can be screened in batches through a backend-only OpenAI runner that validates structured output and persists status/results.
- Operator UI (Streamlit): users browse and filter documents (including keyword tags), inspect full text and PDFs, preview screening excerpts/request payloads, edit screening prompts, inspect source config, and trigger ingestion/refetch/backfill jobs. The dashboard does not directly execute LLM screening calls.
  - the dashboard uses lightweight signed query-param persistence so login survives reloads and document-detail navigation from card links.

## Core Functional Areas

### 1. Ingestion Pipeline
- Entry point: `python main.py`.
- Overlap protection: file lock at `<KA_DATA_DIR>/ingestion.lock`.
- Source loading: `modules/ingest.py` loads canonical sources from `sources.txt` through `config.load_sources_with_status()`.
  - Backward compatibility: if `sources.txt` is absent, legacy `feeds.txt` is mapped to `rss` sources.
- Discovery methods:
  - `rss` -> `modules/discovery_rss.py`
  - `sitemap` -> `modules/discovery_sitemap.py`
  - `listing` -> `modules/discovery_listing.py`
- Storage: only new URLs are inserted (`url_exists` dedupe in `modules/database.py`).
- Database metadata tracks discovery origin:
  - `discovery_method`
  - `discovery_source_url`

### 2. Relevance and Keyword Tagging
- Relevance filtering is implemented in `modules/filter.py`.
- Tier 1:
  - direct-hit keywords from `tier1_keywords.txt` (+ optional `tier1_keywords_en.txt`)
  - any match -> relevant.
- Tier 2:
  - themed keywords from `tier2_keywords.txt`
  - requires context words from `context_words.txt` (+ optional `context_words_en.txt`), or multi-theme co-occurrence.
- For sitemap/listing candidates, relevance text is enriched with page metadata (`<title>`, meta description) before filtering when discovery text is weak.
- Keyword tags:
  - all matched Tier 1 + Tier 2 keywords are stored in `documents.keyword_tags` (JSON array)
  - context words are never stored as tags
  - ingestion extracts tags from `title + discovery summary + fetched text`.

### 3. Freshness and Incremental Discovery (Sitemap/Listing)
- Sitemap/listing sources apply an effective minimum publication date during discovery:
  - `max(6-month cutoff, source checkpoint from DB)`.
- 6-month cutoff is controlled by:
  - `KA_MAX_AGE_DAYS_SITEMAP_LISTING` (default `183`).
- Source checkpoint is computed from latest known `publication_date` / `fetched_at` for that source.
- Result: sitemap/listing runs are incremental by default and avoid historical rescans.

### 4. Content Acquisition
- Implemented in `modules/fetcher.py`.
- URL fetch:
  - `requests` with configured timeout and user-agent.
- PDF path:
  - content-type/URL detection, optional PDF-link discovery on HTML pages, PDF saved to `pdfs/`, text extracted with `pypdf`.
  - for HTML pages with linked PDFs, article text is extracted first and PDF text is appended to `full_text` with delimiter `"[PDF EXTRACT]"`; `content_type` remains `html` and `local_file_path` stores the PDF path.
- HTML path:
  - parse with `BeautifulSoup`, strip clutter tags, extract main/body text.
  - direct PDF URLs remain `content_type = pdf` with PDF-only extracted text.

### 5. Dashboard Operations
- Document browser supports:
  - free-text search (title/full text/source)
  - source/status/PDF/date filters
  - tag filter (`Tags`) with match mode (`Any`/`All`)
  - active filter summary + reset (`Wis filters`).
- Source management page shows multi-source configuration loaded via `load_sources_with_status()`.
- Pipeline page can run ingestion and PDF refetch and display runtime metrics.
- Prompt Studio:
  - edits the 3 screening prompt chunks from `prompts.json`
  - shows the compiled system prompt
  - shows the response schema
  - lets the operator test the exact screening request shape on a sample document.
- Document detail page shows:
  - a reader-first main screen with title, source/date/URL, thumbnail, stored short summary, climate-adaptation relevance, explanation, related opgaven/transities, and compact document metadata
  - a separate `Advanced` subview for technical inspection:
    - full text
    - PDF/download
    - screening excerpt preview
    - reduced LLM input JSON
    - final user message
    - screening metadata and legacy AI output

### 6. Screening Preparation
- Implemented in `modules/screening.py`.
- Step 1 cleanup:
  - normalizes and cleans HTML, PDF, and merged HTML+PDF text
  - preserves the stable delimiter `"[PDF EXTRACT]"`
  - stores cleaned output in `documents.cleaned_text`
- Step 2 payload construction:
  - selects deterministic excerpts from cleaned text
  - uses `keyword_tags`, content type, and PDF heading/keyword heuristics
  - builds a reduced `LLMScreeningRequest` for later API use
  - compiles a structured request shape (`system` prompt + JSON user message).

### 7. Backend LLM Screening
- Implemented in `modules/llm_screening.py` and `screen_documents.py`.
- Step 3 execution:
  - selects eligible documents from the database
  - skips `completed` rows by default
  - can retry `failed` rows or force-rescreen explicitly
  - builds the Step 2 request payload
  - calls OpenAI with the screening prompt and reduced JSON request
  - validates the JSON response against the controlled screening schema
  - persists status, model, input payload, output payload, timestamps, and error text
- Guardrails:
  - backend-only CLI execution; no user-facing trigger in the dashboard
  - configurable batch size, timeout, retries, and model
  - `completed` results are not overwritten unless explicitly forced
  - malformed output is marked `failed` instead of being stored as valid screening output

### 8. Backfill Operations
- PDF backfill:
  - `python refetch_pdfs.py`
- Keyword-tag backfill:
  - `python backfill_tags.py --dry-run`
  - `python backfill_tags.py --only-missing`
  - supports `--limit`, `--since-id`, `--batch-size` for controlled rollout.
- Cleaned-text backfill:
  - `python backfill_cleaned_text.py --dry-run`
  - `python backfill_cleaned_text.py --only-missing`
  - supports `--limit`, `--since-id`, `--batch-size` for controlled rollout.

## Gameplay Loop (Operator Loop)
1. Configure sources, keywords, and prompts in config files/dashboard.
2. Run ingestion via pipeline page (or external `python main.py`).
3. Open document browser and filter to relevant/new documents (including tag filtering when useful).
4. Open a specific document detail page.
5. Inspect the screening preview generated from cleaned text and deterministic excerpt selection.
6. Review the reader-first detail screen for stored screening results; use `Advanced` only when deeper inspection is needed.
7. Open Prompt Studio to tune screening prompts and test the exact request shape on sample documents.
8. Run backend screening in controlled batches via `python screen_documents.py --limit N` when ready.
9. Inspect stored screening results/status in the database or dashboard views.
10. Repeat for remaining documents; optionally run backfill jobs.

## State Model
- `new`
  - assigned when ingestion stores a newly fetched document.
- `analyzed`
  - set when both `ai_summary` and `ai_tasks_json` are present.
- `failed`
  - supported status; UI has badge support.
  - ingestion currently tracks failures in counters (fetch/store/discovery warnings) but does not persist failed placeholder rows.

### Screening Status Model
- `NULL`
  - document has not been screened yet.
- `pending`
  - screening request payload has been prepared and the document is in progress.
- `completed`
  - validated screening output is stored in `screening_output_json`.
- `failed`
  - the most recent screening attempt failed due to API, parsing, or validation problems.

## Reliability and Guardrails
- Ingestion lock:
  - lock file at `<KA_DATA_DIR>/ingestion.lock`
  - stale lock replacement threshold: 2 hours.
- Candidate caps:
  - `KA_MAX_CANDIDATES_PER_SOURCE` (default `60`)
  - per-source override via `options.max_candidates`
  - `KA_MAX_SITEMAP_URLS_PER_SOURCE` (default `120`)
  - per-source override via `options.max_urls`
  - `KA_MAX_SITEMAP_SCAN_URLS_PER_SOURCE` (default `800`)
  - per-source override via `options.max_scan_urls`
  - `KA_MAX_LISTING_PAGES_PER_SOURCE` (default `2`)
  - `KA_MAX_ENTRIES_PER_FEED` (default `50`) for RSS.
- SQLite operational settings:
  - `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`.
- URL deduplication:
  - ingestion skips URLs already present in `documents.url` (unique column).

## Important Interfaces / Public Contracts
- CLI/runtime commands:
  - `python main.py`
  - `streamlit run dashboard.py`
  - `python refetch_pdfs.py`
  - `python backfill_tags.py --only-missing`
  - `python backfill_cleaned_text.py --only-missing`
  - `python screen_documents.py --limit 5`
  - `python screen_documents.py --retry-failed --limit 5`
  - `python screen_documents.py --doc-id 28 --force-rescreen`
- Environment/config controls:
  - `KA_DATA_DIR`
  - `KA_SOURCES_FILE` (preferred)
  - `KA_FEEDS_FILE` (legacy fallback)
  - `KA_DASHBOARD_USERNAME`
  - `KA_DASHBOARD_PASSWORD`
  - `KA_OPENAI_API_KEY`
  - `KA_OPENAI_MODEL`
  - `KA_OPENAI_BASE_URL`
  - `KA_OPENAI_TIMEOUT_SECONDS`
  - `KA_OPENAI_MAX_RETRIES`
  - `KA_SCREENING_BATCH_SIZE`
  - `KA_MAX_CANDIDATES_PER_SOURCE`
  - `KA_MAX_AGE_DAYS_SITEMAP_LISTING`
  - `KA_MAX_SITEMAP_URLS_PER_SOURCE`
  - `KA_MAX_SITEMAP_SCAN_URLS_PER_SOURCE`
  - `KA_MAX_LISTING_PAGES_PER_SOURCE`
  - `KA_MAX_ENTRIES_PER_FEED`
- Database contract:
  - `documents` table includes source metadata, discovery metadata, extracted content, cleaned screening text (`cleaned_text`, version/timestamp), keyword tags (`keyword_tags`), screening execution fields (`screening_status`, timestamps, model, input/output JSON, error), and legacy manual AI output fields.

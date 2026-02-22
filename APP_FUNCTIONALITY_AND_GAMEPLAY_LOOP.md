# App Functionality and Gameplay Loop

## Functional Overview (Current State)
The app operates as a document intelligence workflow with automated ingestion and manual AI analysis completion:
- Automated ingestion: sources are discovered via `rss`, `sitemap`, and `listing` methods, entries are filtered by tiered relevance rules, content is fetched/extracted, and new documents are stored in SQLite.
- Operator UI (Streamlit): users browse and filter documents, inspect full text and PDFs, edit keywords/prompts, inspect source config, and trigger ingestion/refetch jobs.
- Human-in-the-loop AI: the dashboard generates prompts from document text, an operator runs an external AI tool manually, then pastes summary/JSON results back into the app.

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
- Database metadata now tracks discovery origin:
  - `discovery_method`
  - `discovery_source_url`

### 2. Relevance System
- Implemented in `modules/filter.py`.
- Tier 1:
  - direct-hit keywords from `tier1_keywords.txt` (+ optional `tier1_keywords_en.txt`)
  - any match => relevant.
- Tier 2:
  - themed keywords from `tier2_keywords.txt`
  - requires context words from `context_words.txt` (+ optional `context_words_en.txt`), or multi-theme co-occurrence.
- For sitemap/listing candidates, relevance text is enriched with page metadata (`<title>`, meta description) before filtering when discovery text is weak.

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
- HTML path:
  - parse with `BeautifulSoup`, strip clutter tags, extract main/body text.

### 5. Dashboard Operations
- `dashboard.py` page `"📡 RSS Feeds"` now shows multi-source configuration (method + source + URL) loaded via `load_sources_with_status()`.
- `"▶️ Pipeline"` now reflects total configured `Bronnen` (not only RSS feeds).
- Existing document browsing, prompt handling, and manual AI workflow remain unchanged.

### 6. Pipeline and PDF Operations
- `"▶️ Pipeline"` page can:
  - run `python main.py`
  - run `python refetch_pdfs.py`
  - display runtime metrics (new/analyzed counts, PDFs, summaries, tasks).

## Gameplay Loop (Operator Loop)
1. Configure sources, keywords, and prompts in config files/dashboard.
2. Run ingestion via pipeline page (or external `python main.py`).
3. Open document browser and filter to relevant/new documents.
4. Open a specific document detail page.
5. Generate summary/task prompts from `full_text`.
6. Run external AI tool manually with copied prompt text.
7. Paste generated summary and tasks JSON into dashboard fields.
8. Save outputs to DB; once both summary and task JSON exist, status becomes `analyzed`.
9. Repeat for remaining documents; optionally run PDF refetch for items without local PDFs.

## State Model
- `new`
  - assigned when ingestion stores a newly fetched document.
- `analyzed`
  - set when both `ai_summary` and `ai_tasks_json` are present.
- `failed`
  - supported status; UI has badge support.
  - ingestion currently tracks failures in counters (fetch/store/discovery warnings) but does not persist failed placeholder rows.

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
  - `python main.py --test`
  - `streamlit run dashboard.py`
  - `python refetch_pdfs.py`
- Environment/config controls:
  - `KA_DATA_DIR`
  - `KA_SOURCES_FILE` (preferred)
  - `KA_FEEDS_FILE` (legacy fallback)
  - `KA_MAX_CANDIDATES_PER_SOURCE`
  - `KA_MAX_AGE_DAYS_SITEMAP_LISTING`
  - `KA_MAX_SITEMAP_URLS_PER_SOURCE`
  - `KA_MAX_SITEMAP_SCAN_URLS_PER_SOURCE`
  - `KA_MAX_LISTING_PAGES_PER_SOURCE`
  - `KA_MAX_ENTRIES_PER_FEED`
- Database contract:
  - `documents` table includes source metadata, discovery metadata, extracted content, and manual AI output fields.

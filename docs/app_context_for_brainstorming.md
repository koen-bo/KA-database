# Climate Adaptation Knowledge Base: App Context for Brainstorming

## What this application is

This application is a Python-based document intelligence system for climate adaptation. Its purpose is to continuously collect Dutch policy, government, research, and institutional publications, extract their contents, store them in a local database, and make them easy to review through an operator dashboard.

At a high level, the app acts like a specialized monitoring and screening pipeline:

1. It watches many public sources for new documents.
2. It decides which documents are likely relevant to climate adaptation.
3. It downloads and extracts the actual text from web pages and PDFs.
4. It stores each document and its metadata in SQLite.
5. It prepares a compact, structured screening payload from the extracted text.
6. It optionally sends that payload to an LLM for structured analysis.
7. It lets a human operator review documents, prompts, filters, and screening outputs in a Streamlit dashboard.

This is not a public-facing end-user product yet. It is primarily an internal research and operations tool for building and maintaining a high-quality knowledge base of climate adaptation-related documents.

## Core product idea

The core value of the application is reducing the manual effort required to track relevant climate adaptation publications across many fragmented Dutch and European sources.

Instead of manually checking ministry sites, parliamentary feeds, research institutes, sector organizations, and policy portals, the app centralizes discovery and turns raw publications into a searchable, screenable corpus.

Its job is not only to ingest documents, but also to make them operationally useful:

- documents are deduplicated by URL
- source and discovery metadata are preserved
- PDFs can be stored locally
- text is cleaned for downstream screening
- keyword tags are extracted for browsing and filtering
- LLM screening can produce standardized summaries and relevance judgments

## Main user / operator

The current primary user is an operator or analyst who manages the ingestion pipeline and reviews results. This person likely:

- curates sources
- tunes keyword filters
- adjusts screening prompts
- runs ingestion jobs
- reviews new documents
- inspects document details and PDFs
- verifies or interprets screening output

So the app is best understood as an analyst workbench plus a backend ingestion/screening engine.

## Problem it solves

The application addresses a few specific problems:

- relevant climate adaptation information is scattered across many websites and formats
- many sources do not expose information consistently
- important documents may be hidden inside PDFs or mixed article-plus-PDF pages
- not every document from a source is relevant, so filtering is needed before full processing
- manual triage of all incoming documents is slow and hard to scale
- analysts need a stable way to inspect both raw source material and structured screening results

## What kinds of content it ingests

The system ingests public documents and pages from a curated source list in `sources.txt`.

Current source discovery methods:

- `rss`: direct feed-based discovery
- `sitemap`: XML sitemap scanning with include-prefix rules
- `listing`: scraping paginated listing/archive pages using selector templates

The current source mix includes Dutch government, parliament, ministries, research institutes, public agencies, sector organizations, and some European climate-related sources.

Examples of source types already covered:

- Rijksoverheid news and document feeds
- Tweede Kamer RSS
- PBL, RIVM, KNMI, KWR, STOWA
- IPLO, VNG, Unie van Waterschappen
- Deltaprogramma, Deltares, TNO
- selected institutional listing pages and sitemap-only sources

## End-to-end workflow

### 1. Source discovery

The ingestion pipeline loads configured sources and fetches candidate links from each one.

- RSS sources produce entries directly from feeds.
- Sitemap sources scan URLs but apply date-based narrowing so they do not rescan history unnecessarily.
- Listing sources scrape archive/news pages and can paginate a limited number of pages.

The system tracks where a document came from using:

- `discovery_method`
- `discovery_source_url`

### 2. First-pass relevance filtering

Before doing expensive content extraction, the app applies a deterministic relevance filter based on keyword logic.

The filter has two tiers:

- Tier 1: direct-hit keywords, which immediately count as relevant
- Tier 2: more contextual keywords, which require supporting context words or multi-theme co-occurrence

This is designed to reduce noise. It helps the system avoid downloading every document about broad topics like housing, water, agriculture, or infrastructure unless climate adaptation relevance is signaled.

For weak sitemap/listing candidates, the app can enrich the candidate text using page title and meta description before re-checking relevance.

### 3. Content fetching and extraction

Once a candidate passes the filter, the fetcher retrieves the actual content.

The fetcher supports:

- direct HTML pages
- direct PDF links
- HTML pages that link to an important PDF

Important behavior:

- direct PDFs are downloaded locally and text is extracted from the PDF
- HTML pages are cleaned with boilerplate removal and converted into readable text
- if an HTML page has a linked PDF, the app keeps the article text and appends the PDF extract into the same stored text using a stable delimiter: `[PDF EXTRACT]`

This means the stored document can preserve both page context and PDF content in one record.

### 4. Storage

Each accepted document is stored in a local SQLite database (`kennisbank.db`) with metadata, extracted content, and later-stage screening fields.

The app also stores PDFs in a local `pdfs/` directory when relevant.

The `documents` table includes several categories of data:

- source metadata: URL, title, source name, publication date
- discovery metadata: discovery method and source URL
- fetch artifacts: content type, local PDF path, thumbnail URL, fetched timestamp
- text fields: raw/full extracted text and cleaned screening text
- tags and status: keyword tags, processing status, screening status
- LLM screening fields: request payload, response payload, model, timestamps, errors
- legacy AI fields: summary, relevance flag, task/opgave JSON

## Screening pipeline

The app separates document screening into multiple stages.

### Step 1: deterministic text cleanup

Raw extracted text is normalized into `cleaned_text`. This step removes noise and preserves the article/PDF split when a linked PDF exists.

### Step 2: deterministic excerpt selection

The system builds a reduced screening payload from the cleaned text. It does not send full raw documents blindly to the model.

Instead, it chooses excerpts based on document type and heuristics, such as:

- content type (`html` vs `pdf`)
- presence of a linked PDF
- keyword tags
- paragraph quality
- canonical summary-like PDF headings

This creates a compact request object for the LLM that includes:

- title
- source name
- publication date
- keyword tags
- selected excerpt text

### Step 3: backend-only LLM screening

LLM screening is intentionally kept out of the dashboard UI as a direct operator action. It runs through a backend CLI script.

The screening model receives:

- a compiled system prompt from editable prompt sections
- a structured JSON user payload

The expected output is validated and stored only if it conforms to the schema.

The current structured output includes:

- short summary
- climate adaptation relevance score
- relevance explanation
- primary opgave
- related opgaves
- related transities
- cross-domain relevance signal
- cross-domain explanation
- confidence

If the response is malformed or fails validation, the document is marked as failed rather than storing bad output as if it were trustworthy.

## Dashboard / operator interface

The frontend is a Streamlit dashboard (`dashboard.py`) that serves as the operator control panel.

The dashboard currently supports:

- browsing documents in a searchable interface
- filtering by source, status, date, PDF presence, and keyword tags
- viewing document detail pages
- opening stored PDFs
- seeing full extracted text
- previewing the deterministic screening excerpt
- inspecting the reduced LLM input payload
- reviewing stored screening output
- editing screening prompts from `prompts.json`
- viewing source configuration
- triggering ingestion and maintenance jobs

The dashboard is designed for inspection and operations, not for autonomous decision-making. It helps a human understand both the source material and the system's intermediate outputs.

## System architecture

The app is modular and organized around a pipeline plus operator UI.

Main components:

- `main.py`: ingestion orchestrator with lock protection
- `modules/ingest.py`: multi-source ingestion flow
- `modules/discovery_rss.py`: RSS discovery
- `modules/discovery_sitemap.py`: sitemap discovery
- `modules/discovery_listing.py`: listing-page discovery
- `modules/filter.py`: deterministic relevance filtering and keyword tagging
- `modules/fetcher.py`: content retrieval and extraction
- `modules/database.py`: SQLAlchemy models and DB helpers
- `modules/screening.py`: cleanup and screening payload construction
- `modules/llm_screening.py`: OpenAI screening execution and validation
- `screen_documents.py`: backend screening runner
- `dashboard.py`: Streamlit operations UI
- `config.py`: environment variables, file paths, prompts, keywords, source loading

## Important design choices

Several design decisions define the current shape of the product:

### 1. Local-first persistence

The system uses SQLite and local file storage rather than a hosted database or cloud object storage. This keeps the system lightweight and simple to run, but also means it is optimized for single-operator or small-team workflows rather than heavy multi-user scale.

### 2. Curated source intake

The app does not crawl the open web broadly. It relies on a maintained source list and known extraction strategies. This improves precision and trust, but requires ongoing source maintenance.

### 3. Deterministic filtering before LLM use

The system intentionally uses rule-based keyword filtering and deterministic excerpt construction before invoking an LLM. This controls cost, reduces irrelevant calls, and makes the workflow easier to debug.

### 4. Backend-controlled AI execution

The LLM stage is separated from the UI. This reduces accidental usage, keeps execution more controlled, and makes auditing easier.

### 5. Operator-centered review flow

The application assumes human oversight. The current UI is geared toward review, prompt tuning, and pipeline operations rather than fully automated publication or alerting.

## Current status and maturity

The application appears to be beyond prototype stage in terms of core workflow. It already has:

- multiple discovery methods
- operational guardrails
- source configuration
- document storage
- local PDF handling
- keyword-based relevance logic
- deterministic screening preparation
- structured LLM screening
- an authenticated dashboard for operations and review

At the same time, it still feels like an internal product with room to evolve in user experience, collaboration features, analytics, workflow automation, and productization.

## Reliability and guardrails

The app includes several practical safeguards:

- ingestion lock file to prevent overlapping runs
- stale-lock replacement rules
- per-source candidate caps
- freshness cutoffs for sitemap/listing discovery
- URL-based deduplication
- SQLite WAL mode and related PRAGMAs
- screening retry controls
- structured validation of LLM output
- dashboard authentication via environment variables

These choices suggest the system is designed to run regularly and safely, even though it is still a lightweight local application.

## Useful mental model for brainstorming

If another chat is helping brainstorm new functionality, it should think of this application as:

"A local, operator-facing climate policy intelligence platform that discovers documents from curated public sources, filters and extracts relevant content, stores it in a structured knowledge base, prepares compact screening inputs, and supports human review of both raw documents and LLM-generated structured analysis."

Another useful framing:

"It is part scraper, part document repository, part analyst workbench, and part controlled AI screening pipeline."

## Constraints to keep in mind while brainstorming

Any future ideas should respect the current product reality:

- the system is Python-based and local-first
- the main UI is Streamlit
- storage is SQLite plus local PDF files
- source discovery is curated, not open-ended crawling
- LLM usage is backend-controlled and schema-validated
- human oversight is part of the design
- current users are operators/analysts, not a mass public audience

## Areas where new functionality could naturally fit

Without proposing solutions yet, the product has obvious expansion surfaces around:

- source management and onboarding
- analyst workflow efficiency
- document prioritization and alerts
- richer taxonomy/classification
- search, clustering, and trend detection
- collaboration and annotations
- reporting/export workflows
- screening quality control and evaluation
- source health monitoring
- dashboard usability and operational observability

## One-paragraph version

This application is a local climate adaptation knowledge base and analyst workbench built in Python. It continuously discovers new publications from curated Dutch and related policy/research sources via RSS, sitemaps, and listing pages; filters them for likely relevance using deterministic keyword logic; extracts text from web pages and PDFs; stores the results in SQLite with metadata and keyword tags; prepares compact screening payloads from cleaned text; and optionally runs backend-only LLM screening to produce structured summaries and relevance assessments. A Streamlit dashboard lets an operator browse documents, inspect PDFs and extracted text, tune prompts, review screening outputs, and run maintenance or ingestion workflows.

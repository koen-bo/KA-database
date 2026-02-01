PRODUCT BLUEPRINT: Climate Adaptation Knowledge Base
1. Project Overview
We are building an automated pipeline ("The Climate Monitor") that aggregates, processes, and analyzes Dutch policy documents related to Climate Adaptation. Goal: Create a searchable local database of policy documents (PDFs and Webpages) that are automatically analyzed by AI and linked to 21 specific organizational tasks ("Opgaven").

2. Technical Stack
Language: Python 3.10+

Database: SQLite (local file kennisbank.db) using SQLAlchemy (ORM).

Ingestion: feedparser (RSS), requests.

Content Extraction: BeautifulSoup4 (HTML), pypdf (PDF text extraction).

AI Engine: google-generativeai (Gemini API - Free Tier).

Environment: .env file for API keys.

3. System Architecture (The 4 Modules)
The system runs sequentially as a pipeline:

RSS Collector: Finds new URLs.

Content Fetcher: Downloads and extracts full text (HTML/PDF).

AI Analyst: Reads full text, determines relevance, summarizes, and scores against "21 Opgaven".

Data Access: A simple interface to query the data.

4. Module Specifications
Module A: Database Schema (database.py)
We need a single robust table to store source data and AI analysis.

Table: documents

id (Integer, PK): Auto-increment.

url (String, Unique): The direct link to the document.

source_name (String): e.g., "Tweede Kamer", "PBL".

title (String): The original title from RSS.

publication_date (DateTime): From RSS published.

fetched_at (DateTime): Timestamp of local processing.

content_type (String): 'pdf' or 'html'.

full_text (Text): The raw extracted text content (crucial).

processing_status (String): 'new', 'analyzed', 'failed'.

is_relevant (Boolean): AI decision (True/False).

ai_summary (Text): AI generated summary.

ai_tasks_json (JSON/Text): Stored JSON object containing scores for the 21 tasks.

Module B: The Content Fetcher (fetcher.py)
A helper class that handles the physical retrieval of content.

Input: URL string.

Logic:

Perform HTTP GET (with User-Agent to avoid blocks).

Detect Type: Check HTTP headers or file extension.

If PDF:

Download to memory (io.BytesIO).

Use pypdf to extract text from all pages.

If HTML:

Use BeautifulSoup.

Remove clutter: <script>, <style>, <nav>, <footer>, <aside>.

Extract main text.

Error Handling: Return None if fetch fails, do not crash.

Output: Dictionary {'text': string, 'type': 'pdf'/'html'}.

Module C: RSS Ingest (ingest.py)
The main script to run the collection.

Config: A list of RSS feed URLs.

Process:

Iterate through feeds.

For each entry: Check if entry.link exists in DB.

If New:

Log: "Found new item: {title}".

Call ContentFetcher to get the full text.

Save to DB with processing_status = 'new'.

If Existing: Skip.

Module D: AI Analysis Pipeline (analyze.py)
This script processes the 'new' items.

Dependencies: google.generativeai, python-dotenv.

Rate Limiting: Implement a time.sleep(4) between calls to respect the 15 RPM free tier limit.

The Prompt Logic:

System Prompt: Contains the list of "21 Opgaven" (Tasks).

User Prompt: "Analyze this text. 1. Is it relevant? 2. Summarize. 3. Score against the 21 tasks."

Output format: Strict JSON.

Process:

Select rows where processing_status == 'new'.

Loop through rows.

Send full_text (truncated to 20k chars if needed) to Gemini.

Parse JSON response.

Update DB columns (is_relevant, ai_summary, ai_tasks_json) and set status to analyzed.

5. Development Phases
Phase 1: The Foundation (Current Focus)

Set up SQLite Database.

Build the Content Fetcher (HTML/PDF capability).

Build the RSS Ingester.

Result: A database filling up with full-text documents.

Phase 2: The Intelligence

Connect Gemini API.

Build the prompt with the "21 Opgaven".

Process the text in the DB.

6. Implementation Notes for Cursor
Use SQLAlchemy 2.0+ style.

Ensure the fetcher.py is robust against timeouts.

Keep the project structure modular:

main.py (Orchestrator)

/modules folder for database.py, fetcher.py, ai.py.

.env for secrets.
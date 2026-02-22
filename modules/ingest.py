"""
Climate Adaptation Knowledge Base - Multi-Source Ingestion Module

Fetches discovery candidates from rss/sitemap/listing sources, filters by
relevance, downloads content, and stores in database.
"""

from datetime import datetime, timedelta
import os
from typing import Optional

from bs4 import BeautifulSoup
import config
import requests
from config import REQUEST_TIMEOUT, USER_AGENT
from modules.database import add_document, get_latest_source_timestamp, init_db, url_exists
from modules.discovery_listing import discover_listing_candidates
from modules.discovery_rss import Candidate, discover_rss_candidates
from modules.discovery_sitemap import discover_sitemap_candidates
from modules.fetcher import ContentFetcher
from modules.filter import check_relevance, format_filter_result


class MultiSourceIngester:
    """
    Ingests documents from rss/sitemap/listing sources into the knowledge base.
    """

    def __init__(self):
        self.fetcher = ContentFetcher()
        self.max_candidates_per_source = self._load_max_candidates_per_source()
        self.max_age_days_sitemap_listing = self._load_max_age_days_sitemap_listing()
        self.stats = {
            "sources_processed": 0,
            "rss_sources_processed": 0,
            "sitemap_sources_processed": 0,
            "listing_sources_processed": 0,
            "entries_found": 0,
            "entries_skipped_old": 0,
            "entries_enriched": 0,
            "entries_filtered": 0,
            "entries_skipped_existing": 0,
            "entries_fetched": 0,
            "entries_failed": 0,
            "entries_stored": 0,
        }

    def run(self) -> dict:
        """Run the full ingestion pipeline."""
        print("\n" + "=" * 60)
        print("CLIMATE MONITOR - MULTI-SOURCE INGESTION")
        print("=" * 60)
        print(f"Candidate cap per source: {self.max_candidates_per_source}")

        init_db()

        sources, sources_error, sources_path = config.load_sources_with_status()
        if sources_error:
            print(f"\n[WARNING] {sources_error}")
            return self.stats

        if not sources:
            print("\n[WARNING] No sources configured")
            return self.stats

        print(f"\nLoaded {len(sources)} sources from {sources_path}")

        for source in sources:
            self._process_source(source)

        self._print_summary()
        return self.stats

    def _discover_candidates(self, source: config.SourceConfig) -> list[Candidate]:
        method = source["method"]
        min_publication_date = self._get_source_min_publication_date(source)
        if method == "rss":
            self.stats["rss_sources_processed"] += 1
            return discover_rss_candidates(source)
        if method == "sitemap":
            self.stats["sitemap_sources_processed"] += 1
            return discover_sitemap_candidates(source, min_publication_date=min_publication_date)
        if method == "listing":
            self.stats["listing_sources_processed"] += 1
            return discover_listing_candidates(source, min_publication_date=min_publication_date)
        raise RuntimeError(f"Unsupported source method: {method}")

    def _process_source(self, source: config.SourceConfig) -> None:
        method = source["method"]
        name = source["source_name"]
        url = source["url"]
        print(f"\n--- [{name}] ({method}) ---")
        print(f"    Discovering: {url[:80]}...")

        try:
            candidates = self._discover_candidates(source)
        except Exception as e:
            print(f"    [ERROR] Discovery failed: {e}")
            return

        self.stats["sources_processed"] += 1
        print(f"    Discovered {len(candidates)} candidates")

        source_max_candidates = self._get_source_max_candidates(source)
        if len(candidates) > source_max_candidates:
            print(
                f"    Source returned {len(candidates)} candidates; "
                f"processing first {source_max_candidates}."
            )
            candidates = candidates[:source_max_candidates]

        for candidate in candidates:
            self._process_candidate(candidate)

    def _process_candidate(self, candidate: Candidate) -> None:
        self.stats["entries_found"] += 1

        title = candidate.get("title", "No title")
        link = candidate.get("link", "")
        description = candidate.get("summary", "")
        discovery_method = candidate.get("discovery_method", "")
        publication_date = self._coerce_date(candidate.get("publication_date"))

        if not link:
            return

        # First-stage age gate for sitemap/listing candidates to reduce stale noise.
        if discovery_method in {"sitemap", "listing"} and self._is_too_old(publication_date):
            self.stats["entries_skipped_old"] += 1
            return

        title, description = self._enrich_relevance_text(
            title=title,
            description=description,
            link=link,
            discovery_method=discovery_method,
        )

        filter_result = check_relevance(title, description)
        if not filter_result.is_relevant:
            self.stats["entries_filtered"] += 1
            return

        if url_exists(link):
            self.stats["entries_skipped_existing"] += 1
            return

        print(f"\n    [NEW] {title[:70]}...")
        print(f"       {format_filter_result(filter_result)}")

        result = self.fetcher.fetch(link, source_name=candidate["source_name"], title=title)
        if not result:
            print("       [FAILED] Could not fetch content")
            self.stats["entries_failed"] += 1
            return

        self.stats["entries_fetched"] += 1
        pub_date = publication_date

        try:
            doc = add_document(
                url=link,
                source_name=candidate["source_name"],
                title=title,
                publication_date=pub_date,
                content_type=result["type"],
                local_file_path=result["file_path"],
                full_text=result["text"],
                processing_status="new",
                discovery_method=candidate.get("discovery_method"),
                discovery_source_url=candidate.get("discovery_source_url"),
            )
            self.stats["entries_stored"] += 1
            print(f"       [STORED] ID: {doc.id}, {result['type']}, {len(result['text'])} chars")
            if result["file_path"]:
                print(f"       [PDF] Saved: {result['file_path']}")
        except Exception as e:
            print(f"       [ERROR] Database error: {e}")
            self.stats["entries_failed"] += 1

    def _coerce_date(self, date_value: Optional[datetime]) -> Optional[datetime]:
        if isinstance(date_value, datetime):
            return date_value
        return None

    def _load_max_candidates_per_source(self) -> int:
        raw_value = os.getenv("KA_MAX_CANDIDATES_PER_SOURCE", "60")
        try:
            parsed = int(raw_value)
            if parsed <= 0:
                raise ValueError("must be > 0")
            return parsed
        except (ValueError, TypeError):
            print(
                f"[WARNING] Invalid KA_MAX_CANDIDATES_PER_SOURCE='{raw_value}'. "
                "Falling back to 60."
            )
            return 60

    def _get_source_max_candidates(self, source: config.SourceConfig) -> int:
        """
        Resolve per-source candidate processing cap.
        Source option `max_candidates` overrides global default when provided.
        """
        raw_value = source.get("options", {}).get("max_candidates")
        if raw_value is None:
            return self.max_candidates_per_source
        try:
            parsed = int(raw_value)
            if parsed <= 0:
                return self.max_candidates_per_source
            return parsed
        except (TypeError, ValueError):
            return self.max_candidates_per_source

    def _enrich_relevance_text(
        self,
        title: str,
        description: str,
        link: str,
        discovery_method: str,
    ) -> tuple[str, str]:
        """
        Enrich sitemap/listing relevance text with page metadata.

        This improves recall when sitemap/listing discovery provides weak titles
        (e.g. URL slugs or section names).
        """
        if discovery_method not in {"sitemap", "listing"}:
            return title, description

        has_useful_description = bool((description or "").strip())
        has_useful_title = len((title or "").strip()) > 20
        if has_useful_title and has_useful_description:
            return title, description

        try:
            response = requests.get(
                link,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
            meta_desc = ""
            meta_node = soup.find("meta", attrs={"name": "description"})
            if meta_node and meta_node.get("content"):
                meta_desc = meta_node.get("content", "").strip()
            if not meta_desc:
                og_node = soup.find("meta", attrs={"property": "og:description"})
                if og_node and og_node.get("content"):
                    meta_desc = og_node.get("content", "").strip()

            final_title = page_title or title
            final_description = (description or "").strip()
            if meta_desc:
                final_description = f"{final_description} {meta_desc}".strip()

            if final_title != title or final_description != description:
                self.stats["entries_enriched"] += 1

            return final_title, final_description
        except Exception:
            return title, description

    def _load_max_age_days_sitemap_listing(self) -> int:
        """
        Maximum age in days for sitemap/listing candidates.
        Values <= 0 disable age filtering.
        """
        raw_value = os.getenv("KA_MAX_AGE_DAYS_SITEMAP_LISTING", "183")
        try:
            return int(raw_value)
        except (ValueError, TypeError):
            print(
                f"[WARNING] Invalid KA_MAX_AGE_DAYS_SITEMAP_LISTING='{raw_value}'. "
                "Falling back to 183."
            )
            return 183

    def _is_too_old(self, publication_date: Optional[datetime]) -> bool:
        """Return True when publication date is older than configured age cap."""
        if self.max_age_days_sitemap_listing <= 0:
            return False
        if publication_date is None:
            # No date available: keep candidate to avoid dropping potentially relevant items.
            return False

        now = datetime.now(publication_date.tzinfo) if publication_date.tzinfo else datetime.now()
        age_days = (now - publication_date).days
        return age_days > self.max_age_days_sitemap_listing

    def _get_source_min_publication_date(self, source: config.SourceConfig) -> Optional[datetime]:
        """
        Effective min publication date for discovery prefiltering.

        Uses max(6-month cutoff, latest known timestamp for source).
        Applies only to sitemap/listing.
        """
        if source["method"] not in {"sitemap", "listing"}:
            return None

        cutoff = None
        if self.max_age_days_sitemap_listing > 0:
            cutoff = datetime.now() - timedelta(days=self.max_age_days_sitemap_listing)

        checkpoint = get_latest_source_timestamp(source["source_name"])
        if checkpoint is None:
            return cutoff
        if cutoff is None:
            return checkpoint
        return checkpoint if checkpoint > cutoff else cutoff

    def _print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("INGESTION COMPLETE")
        print("=" * 60)
        print(
            f"""
    Sources processed:       {self.stats['sources_processed']}
      - RSS:                {self.stats['rss_sources_processed']}
      - Sitemap:            {self.stats['sitemap_sources_processed']}
      - Listing:            {self.stats['listing_sources_processed']}
    Entries found:          {self.stats['entries_found']}
    Skipped old (S/L):     {self.stats['entries_skipped_old']}
    Enriched meta (S/L):   {self.stats['entries_enriched']}
    Filtered out:           {self.stats['entries_filtered']}
    Already in DB:          {self.stats['entries_skipped_existing']}
    Fetched:                {self.stats['entries_fetched']}
    Failed:                 {self.stats['entries_failed']}
    -----------------------
    NEW documents stored:   {self.stats['entries_stored']}
"""
        )


def run_ingestion() -> dict:
    """Convenience function to run the ingestion pipeline."""
    ingester = MultiSourceIngester()
    return ingester.run()


if __name__ == "__main__":
    run_ingestion()

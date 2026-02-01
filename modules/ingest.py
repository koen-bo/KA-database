"""
Climate Adaptation Knowledge Base - RSS Ingestion Module

Fetches RSS feeds, filters by relevance, downloads content, and stores in database.
"""

from datetime import datetime
from typing import Optional
import time

import feedparser

import config
from modules.database import init_db, add_document, url_exists
from modules.fetcher import ContentFetcher
from modules.filter import check_relevance, format_filter_result


class RSSIngester:
    """
    Ingests documents from RSS feeds into the knowledge base.
    
    Pipeline:
    1. Load RSS feeds from feeds.txt
    2. Parse each feed for entries
    3. Filter entries by tiered keyword system
    4. Check if URL already exists in database
    5. Fetch content (HTML/PDF)
    6. Store in database
    """
    
    def __init__(self):
        """Initialize the ingester."""
        self.fetcher = ContentFetcher()
        self.stats = {
            "feeds_processed": 0,
            "entries_found": 0,
            "entries_filtered": 0,
            "entries_skipped_existing": 0,
            "entries_fetched": 0,
            "entries_failed": 0,
            "entries_stored": 0,
        }
    
    def run(self) -> dict:
        """
        Run the full ingestion pipeline.
        
        Returns:
            Statistics dictionary with counts
        """
        print("\n" + "=" * 60)
        print("CLIMATE MONITOR - RSS INGESTION")
        print("=" * 60)
        
        # Initialize database
        init_db()
        
        # Load feeds
        feeds = config.load_feeds()
        if not feeds:
            print("\n[WARNING] No feeds configured in feeds.txt")
            return self.stats
        
        print(f"\nLoaded {len(feeds)} RSS feeds")
        
        # Process each feed
        for feed_config in feeds:
            self._process_feed(feed_config)
        
        # Print summary
        self._print_summary()
        
        return self.stats
    
    def _process_feed(self, feed_config: dict) -> None:
        """
        Process a single RSS feed.
        
        Args:
            feed_config: Dict with 'url' and 'source_name' keys
        """
        url = feed_config["url"]
        source_name = feed_config["source_name"]
        
        print(f"\n--- [{source_name}] ---")
        print(f"    Fetching: {url[:60]}...")
        
        try:
            feed = feedparser.parse(url)
            
            if feed.bozo and not feed.entries:
                print(f"    [WARNING] Failed to parse feed: {feed.bozo_exception}")
                return
            
            self.stats["feeds_processed"] += 1
            entries = feed.entries
            print(f"    Found {len(entries)} entries")
            
            for entry in entries:
                self._process_entry(entry, source_name)
                
        except Exception as e:
            print(f"    [ERROR] Error processing feed: {e}")
    
    def _process_entry(self, entry, source_name: str) -> None:
        """
        Process a single RSS entry.
        
        Args:
            entry: feedparser entry object
            source_name: Name of the source for logging
        """
        self.stats["entries_found"] += 1
        
        # Extract entry data
        title = entry.get("title", "No title")
        link = entry.get("link", "")
        description = entry.get("summary", entry.get("description", ""))
        
        if not link:
            return
        
        # Step 1: Check relevance filter
        filter_result = check_relevance(title, description)
        
        if not filter_result.is_relevant:
            self.stats["entries_filtered"] += 1
            return
        
        # Step 2: Check if already in database
        if url_exists(link):
            self.stats["entries_skipped_existing"] += 1
            return
        
        # Step 3: Log the match
        print(f"\n    [NEW] {title[:50]}...")
        print(f"       {format_filter_result(filter_result)}")
        
        # Step 4: Fetch content
        result = self.fetcher.fetch(link, source_name=source_name, title=title)
        
        if not result:
            print(f"       [FAILED] Could not fetch content")
            self.stats["entries_failed"] += 1
            return
        
        self.stats["entries_fetched"] += 1
        
        # Step 5: Parse publication date
        pub_date = self._parse_date(entry)
        
        # Step 6: Store in database
        try:
            doc = add_document(
                url=link,
                source_name=source_name,
                title=title,
                publication_date=pub_date,
                content_type=result["type"],
                local_file_path=result["file_path"],
                full_text=result["text"],
                processing_status="new"
            )
            self.stats["entries_stored"] += 1
            print(f"       [STORED] ID: {doc.id}, {result['type']}, {len(result['text'])} chars")
            
            if result["file_path"]:
                print(f"       [PDF] Saved: {result['file_path']}")
                
        except Exception as e:
            print(f"       [ERROR] Database error: {e}")
            self.stats["entries_failed"] += 1
    
    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse publication date from RSS entry."""
        # Try different date fields
        for field in ["published_parsed", "updated_parsed", "created_parsed"]:
            parsed = entry.get(field)
            if parsed:
                try:
                    return datetime(*parsed[:6])
                except:
                    pass
        return None
    
    def _print_summary(self) -> None:
        """Print ingestion summary."""
        print("\n" + "=" * 60)
        print("INGESTION COMPLETE")
        print("=" * 60)
        print(f"""
    Feeds processed:      {self.stats['feeds_processed']}
    Entries found:        {self.stats['entries_found']}
    Filtered out:         {self.stats['entries_filtered']}
    Already in DB:        {self.stats['entries_skipped_existing']}
    Fetched:              {self.stats['entries_fetched']}
    Failed:               {self.stats['entries_failed']}
    ---------------------
    NEW documents stored: {self.stats['entries_stored']}
""")


def run_ingestion() -> dict:
    """
    Convenience function to run the ingestion pipeline.
    
    Returns:
        Statistics dictionary
    """
    ingester = RSSIngester()
    return ingester.run()


if __name__ == "__main__":
    run_ingestion()

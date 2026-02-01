"""
Climate Adaptation Knowledge Base - Pipeline Test Script

This script tests the full pipeline without needing live RSS feeds.
It uses sample data to verify filtering, fetching, and database storage.
"""

from datetime import datetime

from modules.database import init_db, add_document, get_session, Document
from modules.fetcher import ContentFetcher
from modules.filter import check_relevance, is_relevant, format_filter_result
import config


# =============================================================================
# TEST DATA - Mix of relevant and irrelevant items
# =============================================================================

TEST_ITEMS = [
    # Tier 1 - Direct hits (should always pass)
    {
        "title": "Nieuwe klimaatadaptatie strategie voor Nederlandse steden",
        "description": "Het kabinet presenteert een nieuw plan voor klimaatbestendig bouwen.",
        "expected": "Tier 1"
    },
    {
        "title": "Deltaprogramma 2026: Waterveiligheid in een veranderend klimaat",
        "description": "Jaarlijkse update over de voortgang van het deltaprogramma.",
        "expected": "Tier 1"
    },
    {
        "title": "Klimaatstresstest wijst op risico's hittestress binnenstad",
        "description": "Gemeente voert stresstest uit en vindt knelpunten.",
        "expected": "Tier 1"
    },
    
    # Tier 2 - Context dependent (should pass with context words)
    {
        "title": "Extreme neerslag veroorzaakt wateroverlast in Limburg",
        "description": "Risico op overstromingen neemt toe door klimaatverandering.",
        "expected": "Tier 2 (context: klimaatverandering, risico)"
    },
    {
        "title": "Aanpassing rioolcapaciteit nodig voor toekomst",
        "description": "Gemeente investeert in waterberging voor extreme buien.",
        "expected": "Tier 2 (context: aanpassing, toekomst)"
    },
    {
        "title": "Bodemdaling en funderingsschade in veenweidegebied",
        "description": "Multi-theme match: Landbouw_Natuur + Wonen_Werken_Infra",
        "expected": "Tier 2 (multi-theme)"
    },
    
    # Should be FILTERED OUT (no context)
    {
        "title": "Nieuwe woningbouw in gemeente Almere",
        "description": "Er worden 500 nieuwe woningen gebouwd.",
        "expected": "Filtered"
    },
    {
        "title": "Landbouwsubsidies voor boeren verhoogd",
        "description": "Minister kondigt extra steun aan voor agrarische sector.",
        "expected": "Filtered"
    },
    {
        "title": "Wateroverlast in kelder door lekkende leiding",
        "description": "Particulier heeft last van wateroverlast door defecte kraan.",
        "expected": "Filtered (no context - just 'wateroverlast' alone)"
    },
]


def test_tiered_filter():
    """Test the tiered keyword filter with sample data."""
    print("\n" + "=" * 70)
    print("TESTING TIERED KEYWORD FILTER")
    print("=" * 70)
    
    # Show loaded keywords from files
    tier1 = config.load_tier1_keywords()
    tier2_themes = config.load_tier2_themes()
    tier2_count = sum(len(kws) for kws in tier2_themes.values())
    context = config.load_context_words()
    
    print(f"\nLoaded from text files:")
    print(f"  - tier1_keywords.txt: {len(tier1)} keywords")
    print(f"  - tier2_keywords.txt: {tier2_count} keywords in {len(tier2_themes)} themes")
    print(f"    Themes: {', '.join(tier2_themes.keys())}")
    print(f"  - context_words.txt: {len(context)} words")
    
    print("\n" + "-" * 70)
    print("Testing filter on sample items:\n")
    
    passed = 0
    failed = 0
    
    for item in TEST_ITEMS:
        result = check_relevance(item["title"], item["description"])
        status = format_filter_result(result)
        
        # Determine if result matches expectation
        expected_relevant = item["expected"] != "Filtered"
        match = "✓" if result.is_relevant == expected_relevant else "✗"
        
        if result.is_relevant == expected_relevant:
            passed += 1
        else:
            failed += 1
        
        print(f"{match} [{item['expected']}]")
        print(f"   Title: {item['title'][:60]}...")
        print(f"   Result: {status}")
        print()
    
    print("-" * 70)
    print(f"Results: {passed} passed, {failed} failed")


def test_fetcher():
    """Test the content fetcher with a real URL."""
    print("\n" + "=" * 70)
    print("TESTING CONTENT FETCHER")
    print("=" * 70)
    
    fetcher = ContentFetcher()
    
    # Test with a simple, reliable URL
    test_url = "https://httpbin.org/html"
    print(f"\nFetching test URL: {test_url}")
    
    result = fetcher.fetch(test_url, source_name="Test", title="HTTPBin HTML Test")
    
    if result:
        print(f"  ✓ Success!")
        print(f"    Type: {result['type']}")
        print(f"    Text length: {len(result['text'])} characters")
        print(f"    File path: {result['file_path']}")
        print(f"    Preview: {result['text'][:150]}...")
    else:
        print("  ✗ Failed to fetch content")


def test_database():
    """Test database operations."""
    print("\n" + "=" * 70)
    print("TESTING DATABASE")
    print("=" * 70)
    
    print("\nInitializing database...")
    init_db()
    
    # Add a test document
    test_doc = {
        "url": f"https://test.example.com/doc_{datetime.now().timestamp()}",
        "source_name": "Test Source",
        "title": "Test Document - Klimaatadaptatie Pipeline",
        "publication_date": datetime.now(),
        "content_type": "html",
        "full_text": "Dit is test content over klimaatadaptatie en waterbeheer.",
        "processing_status": "new"
    }
    
    print(f"\nAdding test document: {test_doc['title']}")
    doc = add_document(**test_doc)
    print(f"  ✓ Document added with ID: {doc.id}")
    
    with get_session() as session:
        count = session.query(Document).count()
        print(f"\nTotal documents in database: {count}")


def test_feeds_config():
    """Test RSS feeds configuration loading."""
    print("\n" + "=" * 70)
    print("TESTING FEEDS CONFIGURATION")
    print("=" * 70)
    
    feeds = config.load_feeds()
    print(f"\nLoaded {len(feeds)} RSS feeds from feeds.txt:")
    
    for i, feed in enumerate(feeds[:5], 1):
        print(f"  {i}. [{feed['source_name']}]")
        print(f"     {feed['url'][:60]}...")
    
    if len(feeds) > 5:
        print(f"  ... and {len(feeds) - 5} more")


def main():
    """Run all tests."""
    print("\n" + "#" * 70)
    print("#  CLIMATE ADAPTATION KNOWLEDGE BASE - PIPELINE TEST")
    print("#" * 70)
    
    test_tiered_filter()
    test_feeds_config()
    test_database()
    # test_fetcher()  # Uncomment to test with real HTTP request
    
    print("\n" + "=" * 70)
    print("TESTS COMPLETED")
    print("=" * 70)
    print("\nUncomment test_fetcher() in main() to test HTTP fetching.")
    print("Edit tier1_keywords.txt to add/remove direct-hit keywords.")
    print("Edit config.py TIER_2_THEMES to adjust context-dependent keywords.\n")


if __name__ == "__main__":
    main()

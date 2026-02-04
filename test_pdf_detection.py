"""
Test script for smarter PDF detection.

Tests that:
1. News articles (like Unie van Waterschappen) keep HTML, don't fetch sidebar PDFs
2. Document pages (like PBL publications) still fetch the main PDF
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from modules.fetcher import ContentFetcher

def test_url(url: str, title: str, expected_type: str):
    """Test a URL and show what the fetcher does."""
    print(f"\n{'='*70}")
    print(f"Testing: {title}")
    print(f"URL: {url}")
    print(f"Expected: {expected_type}")
    print("-" * 70)
    
    fetcher = ContentFetcher()
    result = fetcher.fetch(url, source_name="Test", title=title)
    
    if result:
        actual_type = result["type"]
        has_pdf = "Yes" if result["file_path"] else "No"
        text_preview = result["text"][:200].replace("\n", " ") if result["text"] else "No text"
        
        print(f"Result type: {actual_type}")
        print(f"PDF saved: {has_pdf}")
        if result["file_path"]:
            print(f"PDF path: {result['file_path']}")
        print(f"Text preview: {text_preview}...")
        
        # Check if result matches expectation
        if actual_type == expected_type:
            print(f"\n✅ PASS: Got expected type '{expected_type}'")
            return True
        else:
            print(f"\n❌ FAIL: Expected '{expected_type}', got '{actual_type}'")
            return False
    else:
        print("❌ FAIL: No result returned")
        return False


def main():
    print("=" * 70)
    print("SMARTER PDF DETECTION TEST")
    print("=" * 70)
    
    tests = [
        # News articles - should keep HTML, NOT fetch sidebar PDFs
        {
            "url": "https://unievanwaterschappen.nl/wetgevingsoverleg-water-hier-ging-het-over-in-de-tweede-kamer/",
            "title": "Wetgevingsoverleg Water: hier ging het over in de Tweede Kamer",
            "expected": "html",
            "description": "News article with 'gerelateerde publicaties' sidebar"
        },
        
        # Document pages - SHOULD fetch PDF
        {
            "url": "https://www.pbl.nl/publicaties/klimaatrisicos-in-nederland",
            "title": "Klimaatrisico's in Nederland",
            "expected": "pdf",
            "description": "PBL publication page with main document PDF"
        },
        
        # Another news-style page
        {
            "url": "https://www.rijksoverheid.nl/onderwerpen/klimaatverandering",
            "title": "Klimaatverandering",
            "expected": "html",
            "description": "Rijksoverheid info page (no main PDF)"
        },
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        print(f"\n📋 {test['description']}")
        if test_url(test["url"], test["title"], test["expected"]):
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

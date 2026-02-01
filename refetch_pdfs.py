"""
Re-fetch documents to download their PDFs.

This script finds documents that don't have a local PDF file
and attempts to find and download any associated PDFs.

Run with: python refetch_pdfs.py
"""

from modules.database import get_session, Document
from modules.fetcher import ContentFetcher


def refetch_documents_with_pdfs(limit: int = None):
    """
    Re-fetch documents that might have PDFs but weren't downloaded.
    
    Args:
        limit: Optional limit on number of documents to process
    """
    
    fetcher = ContentFetcher()
    
    with get_session() as session:
        # Find ALL documents without a local PDF file
        query = session.query(Document).filter(
            Document.local_file_path == None
        ).order_by(Document.id)
        
        if limit:
            query = query.limit(limit)
        
        docs = query.all()
        
        print(f"Found {len(docs)} documents without PDFs\n")
        print("=" * 60)
        
        updated = 0
        skipped = 0
        
        for doc in docs:
            print(f"\n[{doc.id}] {doc.title[:60] if doc.title else 'No title'}...")
            print(f"    Source: {doc.source_name}")
            print(f"    URL: {doc.url[:70]}...")
            
            result = fetcher.fetch(doc.url, doc.source_name or "Unknown", doc.title or "")
            
            if result and result["file_path"]:
                # Update document with PDF info
                doc.content_type = result["type"]
                doc.local_file_path = result["file_path"]
                doc.full_text = result["text"]
                session.commit()
                
                print(f"    [OK] PDF saved: {result['file_path']}")
                updated += 1
            else:
                print(f"    [SKIP] No PDF found on page")
                skipped += 1
        
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"  Documents processed: {len(docs)}")
        print(f"  PDFs downloaded: {updated}")
        print(f"  No PDF found: {skipped}")


if __name__ == "__main__":
    import sys
    
    # Allow optional limit argument
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            print(f"Processing up to {limit} documents\n")
        except ValueError:
            pass
    
    refetch_documents_with_pdfs(limit)

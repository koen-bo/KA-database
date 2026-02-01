"""
Climate Adaptation Knowledge Base - Main Orchestrator

This is the main entry point for running the pipeline.
Can be run locally or via GitHub Actions.

Usage:
    python main.py           # Run full ingestion pipeline
    python main.py --test    # Run tests only (no ingestion)
"""

import sys

from modules.database import init_db
from modules.ingest import run_ingestion


def main():
    """Run the Climate Monitor pipeline."""
    
    # Check for test mode
    if "--test" in sys.argv:
        print("Running in test mode...")
        from test_pipeline import main as run_tests
        run_tests()
        return
    
    # Run the full ingestion pipeline
    print("\n" + "#" * 60)
    print("#  CLIMATE ADAPTATION KNOWLEDGE BASE")
    print("#  Automated Policy Document Monitor")
    print("#" * 60)
    
    # Run ingestion (this also initializes the database)
    stats = run_ingestion()
    
    # Report results
    if stats["entries_stored"] > 0:
        print(f"\n[SUCCESS] Added {stats['entries_stored']} new documents!")
    else:
        print("\n[INFO] No new relevant documents found today.")
    
    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()

"""
Backfill cleaned text for existing documents.

Usage examples:
    python backfill_cleaned_text.py --dry-run
    python backfill_cleaned_text.py --only-missing
    python backfill_cleaned_text.py --limit 500
    python backfill_cleaned_text.py --since-id 10000
"""

import argparse
import sys
from typing import Optional

from modules.database import (
    init_db,
    iter_documents_for_cleaned_text_backfill,
    update_document_cleaned_text,
)
from modules.screening import clean_document_text


def _is_missing_cleaned_text(raw_value: Optional[str]) -> bool:
    return raw_value is None or raw_value.strip() == ""


def run_backfill(
    dry_run: bool = False,
    only_missing: bool = False,
    limit: Optional[int] = None,
    since_id: int = 0,
    batch_size: int = 200,
) -> int:
    """
    Returns process exit code.
    """
    init_db()

    scanned = 0
    updated = 0
    unchanged = 0
    skipped_empty_text = 0
    errors = 0
    preview_budget = 10

    print("Starting cleaned text backfill...")
    print(
        f"Options: dry_run={dry_run}, only_missing={only_missing}, "
        f"limit={limit}, since_id={since_id}, batch_size={batch_size}"
    )

    for doc in iter_documents_for_cleaned_text_backfill(
        since_id=since_id,
        limit=limit,
        batch_size=batch_size,
    ):
        scanned += 1

        if only_missing and not _is_missing_cleaned_text(doc.cleaned_text):
            unchanged += 1
            continue

        full_text = doc.full_text or ""
        if not full_text.strip():
            skipped_empty_text += 1
            continue

        cleanup_result = clean_document_text(
            full_text=full_text,
            content_type=doc.content_type,
            local_file_path=doc.local_file_path,
        )
        new_text = cleanup_result.cleaned_text
        current_text = (doc.cleaned_text or "").strip()

        if current_text == new_text and doc.cleaned_text_version == cleanup_result.cleanup_version:
            unchanged += 1
            continue

        if dry_run:
            updated += 1
            if preview_budget > 0:
                print(
                    f"[DRY-RUN] doc_id={doc.id} "
                    f"old_len={len(current_text)} new_len={len(new_text)} "
                    f"has_pdf_section={cleanup_result.has_pdf_section}"
                )
                preview_budget -= 1
            continue

        try:
            ok = update_document_cleaned_text(
                doc.id,
                cleaned_text=new_text,
                version=cleanup_result.cleanup_version,
            )
            if ok:
                updated += 1
            else:
                errors += 1
                print(f"[ERROR] Could not update doc_id={doc.id}")
        except Exception as exc:
            errors += 1
            print(f"[ERROR] doc_id={doc.id}: {exc}")

    print("\nBackfill complete.")
    print(f"  scanned: {scanned}")
    print(f"  updated: {updated}")
    print(f"  unchanged: {unchanged}")
    print(f"  skipped-empty-text: {skipped_empty_text}")
    print(f"  errors: {errors}")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill cleaned text for documents.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes without writing to the database.",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only process documents where cleaned_text is missing or empty.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of documents to scan.",
    )
    parser.add_argument(
        "--since-id",
        type=int,
        default=0,
        help="Only process documents with id > since-id.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Streaming batch size for DB reads.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return run_backfill(
        dry_run=args.dry_run,
        only_missing=args.only_missing,
        limit=args.limit,
        since_id=args.since_id,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    sys.exit(main())

"""
Backfill keyword tags for existing documents.

Usage examples:
    python backfill_tags.py --dry-run
    python backfill_tags.py --only-missing
    python backfill_tags.py --limit 500
    python backfill_tags.py --since-id 10000
"""

import argparse
import json
import sys
from typing import Optional

from modules.database import (
    init_db,
    iter_documents_for_tag_backfill,
    update_document_tags,
)
from modules.filter import extract_keyword_tags


def _is_missing_tags(raw_value: Optional[str]) -> bool:
    if raw_value is None:
        return True
    parsed = raw_value.strip()
    return parsed == "" or parsed == "[]"


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

    print("Starting keyword tag backfill...")
    print(
        f"Options: dry_run={dry_run}, only_missing={only_missing}, "
        f"limit={limit}, since_id={since_id}, batch_size={batch_size}"
    )

    for doc in iter_documents_for_tag_backfill(
        since_id=since_id,
        limit=limit,
        batch_size=batch_size,
    ):
        scanned += 1

        current_tags_json = doc.keyword_tags
        if only_missing and not _is_missing_tags(current_tags_json):
            unchanged += 1
            continue

        title = doc.title or ""
        full_text = doc.full_text or ""
        text = f"{title} {full_text}".strip()
        if not text:
            skipped_empty_text += 1
            continue

        new_tags = extract_keyword_tags(text)
        new_tags_json = json.dumps(new_tags, ensure_ascii=False)

        current_tags = []
        if current_tags_json:
            try:
                parsed = json.loads(current_tags_json)
                if isinstance(parsed, list):
                    current_tags = sorted([str(item) for item in parsed])
            except Exception:
                # Invalid JSON in old rows should be replaced on write mode.
                pass

        if current_tags == new_tags:
            unchanged += 1
            continue

        if dry_run:
            updated += 1
            if preview_budget > 0:
                print(
                    f"[DRY-RUN] doc_id={doc.id} "
                    f"old={len(current_tags)} new={len(new_tags)}"
                )
                preview_budget -= 1
            continue

        try:
            ok = update_document_tags(doc.id, new_tags_json)
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
    parser = argparse.ArgumentParser(description="Backfill keyword tags for documents.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes without writing to the database.",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only process documents where keyword_tags is missing or empty.",
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

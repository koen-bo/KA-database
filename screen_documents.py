"""
Backend-controlled Step 3 screening runner.

Screens eligible documents with the configured OpenAI model and stores
validated structured output in SQLite.
"""

from __future__ import annotations

import argparse

import config
from modules.database import (
    init_db,
    iter_documents_for_screening,
    mark_document_screening_completed,
    mark_document_screening_failed,
    mark_document_screening_pending,
)
from modules.llm_screening import screen_document
from modules.screening import build_llm_screening_request, build_screening_input, serialize_llm_screening_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen eligible documents with OpenAI.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--since-id", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=config.SCREENING_BATCH_SIZE)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--force-rescreen", action="store_true")
    parser.add_argument("--doc-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    init_db()

    processed = 0
    completed = 0
    failed = 0

    for doc in iter_documents_for_screening(
        since_id=args.since_id,
        limit=args.limit,
        batch_size=args.batch_size,
        retry_failed=args.retry_failed,
        force_rescreen=args.force_rescreen,
        doc_id=args.doc_id,
    ):
        processed += 1
        title = doc.title or f"Document {doc.id}"
        print(f"[{doc.id}] Screening: {title}")

        screening_input = build_screening_input(doc)
        llm_request = build_llm_screening_request(screening_input)
        input_json = serialize_llm_screening_request(llm_request)

        if args.dry_run:
            print(f"  dry-run: would screen with model={config.OPENAI_MODEL}")
            continue

        if not mark_document_screening_pending(doc.id, input_json, config.OPENAI_MODEL):
            print("  failed: document not found while marking pending")
            failed += 1
            continue

        result = screen_document(doc)

        if result.success and result.output_json:
            mark_document_screening_completed(
                doc.id,
                input_json,
                result.output_json,
                result.model,
            )
            completed += 1
            print("  completed")
        else:
            mark_document_screening_failed(
                doc.id,
                input_json,
                result.model,
                result.error_text or "unknown screening error",
            )
            failed += 1
            print(f"  failed: {result.error_text}")

    print(
        f"Done. processed={processed} completed={completed} failed={failed} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

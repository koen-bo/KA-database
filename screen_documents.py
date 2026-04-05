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
    mark_document_exploratory_completed,
    mark_document_exploratory_failed,
    mark_document_exploratory_pending,
    mark_document_screening_completed,
    mark_document_screening_failed,
    mark_document_screening_pending,
)
from modules.llm_screening import (
    prepare_document_for_screening,
    prepare_exploratory_prompt,
    screen_exploratory_document,
    screen_factual_document,
)
from modules.screening_context import annotate_context_selection_with_factual_footholds, merge_context_metadata


SCREENING_VERSION = "two_lane_v3_normalized"


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
    prompts = config.load_prompts()

    processed = 0
    completed = 0
    failed = 0
    exploratory_completed = 0
    exploratory_failed = 0

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
        prepared = prepare_document_for_screening(document=doc, prompts=prompts)

        if args.dry_run:
            print(f"  dry-run: would run factual + exploratory screening with model={config.OPENAI_MODEL}")
            continue

        if not mark_document_screening_pending(
            doc.id,
            prepared.factual_input_json,
            config.OPENAI_MODEL,
            screening_version=SCREENING_VERSION,
            context_json=prepared.context_json,
        ):
            print("  failed: document not found while marking pending")
            failed += 1
            continue

        factual_result = screen_factual_document(prepared)

        if factual_result.success and factual_result.output_json and factual_result.output:
            factual_context_json = annotate_context_selection_with_factual_footholds(
                prepared.context_json,
                [item.id for item in factual_result.output.footholds],
            )
            factual_context_json = merge_context_metadata(
                factual_context_json,
                factual_validation_warnings=factual_result.warnings or [],
                factual_repairs_applied=factual_result.repairs_applied or [],
            )
            mark_document_screening_completed(
                doc.id,
                prepared.factual_input_json,
                factual_result.output_json,
                factual_result.model,
                screening_version=SCREENING_VERSION,
                context_json=factual_context_json,
            )
            completed += 1
            print("  factual completed")
        else:
            mark_document_screening_failed(
                doc.id,
                prepared.factual_input_json,
                factual_result.model,
                factual_result.error_text or "unknown factual screening error",
                screening_version=SCREENING_VERSION,
                context_json=prepared.context_json,
            )
            failed += 1
            print(f"  factual failed: {factual_result.error_text}")
            continue

        _, exploratory_input_json, _, _ = prepare_exploratory_prompt(
            prepared,
            factual_output=factual_result.output,
            prompts=prompts,
        )

        if not mark_document_exploratory_pending(
            doc.id,
            exploratory_input_json,
            config.OPENAI_MODEL,
            context_json=factual_context_json,
        ):
            exploratory_failed += 1
            print("  exploratory failed: document not found while marking pending")
            continue

        exploratory_result = screen_exploratory_document(
            prepared,
            factual_output=factual_result.output,
            prompts=prompts,
        )

        if exploratory_result.success and exploratory_result.output_json:
            exploratory_context_json = merge_context_metadata(
                factual_context_json,
                exploratory_validation_warnings=exploratory_result.warnings or [],
                exploratory_repairs_applied=exploratory_result.repairs_applied or [],
            )
            mark_document_exploratory_completed(
                doc.id,
                exploratory_input_json,
                exploratory_result.output_json,
                exploratory_result.model,
                context_json=exploratory_context_json,
            )
            exploratory_completed += 1
            print("  exploratory completed")
        else:
            exploratory_context_json = merge_context_metadata(
                factual_context_json,
                exploratory_validation_warnings=exploratory_result.warnings or [],
                exploratory_repairs_applied=exploratory_result.repairs_applied or [],
            )
            mark_document_exploratory_failed(
                doc.id,
                exploratory_input_json,
                exploratory_result.model,
                exploratory_result.error_text or "unknown exploratory screening error",
                context_json=exploratory_context_json,
            )
            exploratory_failed += 1
            print(f"  exploratory failed: {exploratory_result.error_text}")

    print(
        "Done. "
        f"processed={processed} "
        f"factual_completed={completed} "
        f"factual_failed={failed} "
        f"exploratory_completed={exploratory_completed} "
        f"exploratory_failed={exploratory_failed} "
        f"dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

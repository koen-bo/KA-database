import json
import os
import sys
import uuid
import unittest
from unittest import mock

import config
import screen_documents
from modules import database
from modules.database import (
    add_document,
    get_session,
    iter_documents_for_screening,
    mark_document_screening_completed,
    mark_document_screening_failed,
)
from modules.llm_screening import ScreeningRunResult, screen_document


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def _set_temp_database(testcase: unittest.TestCase):
    testcase._old_db_path = config.DATABASE_PATH
    testcase._temp_db_path = os.path.join(
        os.getcwd(),
        f"test_screening_{uuid.uuid4().hex}.db",
    )
    config.DATABASE_PATH = testcase._temp_db_path
    database._engine = None
    database._SessionLocal = None
    database.init_db()


def _restore_database(testcase: unittest.TestCase):
    if database._engine is not None:
        database._engine.dispose()
    config.DATABASE_PATH = testcase._old_db_path
    database._engine = None
    database._SessionLocal = None
    for path in (
        testcase._temp_db_path,
        f"{testcase._temp_db_path}-shm",
        f"{testcase._temp_db_path}-wal",
    ):
        if os.path.exists(path):
            os.remove(path)


class LlmScreeningModuleTests(unittest.TestCase):
    def setUp(self):
        self.old_api_key = config.OPENAI_API_KEY
        self.old_model = config.OPENAI_MODEL
        self.old_retries = config.OPENAI_MAX_RETRIES
        self.old_timeout = config.OPENAI_TIMEOUT_SECONDS
        self.old_base_url = config.OPENAI_BASE_URL
        config.OPENAI_API_KEY = "test-key"
        config.OPENAI_MODEL = "test-model"
        config.OPENAI_MAX_RETRIES = 0
        config.OPENAI_TIMEOUT_SECONDS = 5
        config.OPENAI_BASE_URL = "https://example.invalid/v1"

    def tearDown(self):
        config.OPENAI_API_KEY = self.old_api_key
        config.OPENAI_MODEL = self.old_model
        config.OPENAI_MAX_RETRIES = self.old_retries
        config.OPENAI_TIMEOUT_SECONDS = self.old_timeout
        config.OPENAI_BASE_URL = self.old_base_url

    def _document(self):
        return {
            "id": 1,
            "url": "https://example.com/doc",
            "title": "Duingras versnelt duinvorming",
            "source_name": "Nature Today",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "html",
            "cleaned_text": (
                "Onderzoek laat zien hoe duingras de vorming van natuurlijke duinen versnelt "
                "en wat dit betekent voor klimaatadaptatie, kustveiligheid en gebiedsgerichte uitvoering."
            ),
            "keyword_tags": json.dumps(["klimaatadaptatie", "kustveiligheid"]),
        }

    def test_valid_structured_response_is_accepted(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "short_summary": "Samenvatting.",
                                "climate_adaptation_relevance_score": 7,
                                "climate_adaptation_explanation": "Relevant voor klimaatadaptatie en bruikbaar voor RVO.",
                                "primary_opgave": "klimaatadaptatie",
                                "related_opgaves": [],
                                "related_transities": [],
                                "cross_domain_relevance_signal": "none",
                                "cross_domain_explanation": "none",
                                "confidence": 0.8,
                            }
                        )
                    }
                }
            ]
        }

        result = screen_document(self._document(), post_func=lambda *args, **kwargs: FakeResponse(payload))

        self.assertTrue(result.success)
        self.assertIsNotNone(result.output_json)
        self.assertEqual(result.output.primary_opgave, "klimaatadaptatie")

    def test_malformed_json_is_rejected(self):
        payload = {"choices": [{"message": {"content": "{not valid json}"}}]}

        result = screen_document(self._document(), post_func=lambda *args, **kwargs: FakeResponse(payload))

        self.assertFalse(result.success)
        self.assertIn("Expecting property name", result.error_text)

    def test_invalid_enum_label_is_rejected(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "short_summary": "Samenvatting.",
                                "climate_adaptation_relevance_score": 7,
                                "climate_adaptation_explanation": "Relevant voor klimaatadaptatie en bruikbaar voor RVO.",
                                "primary_opgave": "vrije_keuze",
                                "related_opgaves": [],
                                "related_transities": [],
                                "cross_domain_relevance_signal": "none",
                                "cross_domain_explanation": "none",
                                "confidence": 0.8,
                            }
                        )
                    }
                }
            ]
        }

        result = screen_document(self._document(), post_func=lambda *args, **kwargs: FakeResponse(payload))

        self.assertFalse(result.success)
        self.assertIn("primary_opgave", result.error_text)

    def test_missing_required_field_is_rejected(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "short_summary": "Samenvatting.",
                                "climate_adaptation_relevance_score": 7,
                                "primary_opgave": "klimaatadaptatie",
                                "related_opgaves": [],
                                "related_transities": [],
                                "cross_domain_relevance_signal": "none",
                                "cross_domain_explanation": "none",
                                "confidence": 0.8,
                            }
                        )
                    }
                }
            ]
        }

        result = screen_document(self._document(), post_func=lambda *args, **kwargs: FakeResponse(payload))

        self.assertFalse(result.success)
        self.assertIn("climate_adaptation_explanation", result.error_text)


class ScreeningPersistenceTests(unittest.TestCase):
    def setUp(self):
        _set_temp_database(self)

    def tearDown(self):
        _restore_database(self)

    def _create_docs(self):
        doc_new = add_document(
            url="https://example.com/new",
            source_name="Bron",
            title="Nieuw document",
            full_text="Tekst",
            content_type="html",
        )
        doc_failed = add_document(
            url="https://example.com/failed",
            source_name="Bron",
            title="Mislukt document",
            full_text="Tekst",
            content_type="html",
        )
        doc_completed = add_document(
            url="https://example.com/completed",
            source_name="Bron",
            title="Voltooid document",
            full_text="Tekst",
            content_type="html",
        )
        mark_document_screening_failed(doc_failed.id, "{}", "test-model", "bad json")
        mark_document_screening_completed(doc_completed.id, "{}", '{"ok": true}', "test-model")
        return doc_new, doc_failed, doc_completed

    def test_completed_documents_skipped_by_default(self):
        doc_new, doc_failed, doc_completed = self._create_docs()

        docs = list(iter_documents_for_screening())

        self.assertEqual([doc.id for doc in docs], [doc_new.id])

    def test_failed_documents_included_only_with_retry_failed(self):
        doc_new, doc_failed, _ = self._create_docs()

        docs = list(iter_documents_for_screening(retry_failed=True))

        self.assertEqual([doc.id for doc in docs], [doc_new.id, doc_failed.id])

    def test_completed_documents_included_with_force_rescreen(self):
        doc_new, doc_failed, doc_completed = self._create_docs()

        docs = list(iter_documents_for_screening(retry_failed=True, force_rescreen=True))

        self.assertEqual([doc.id for doc in docs], [doc_new.id, doc_failed.id, doc_completed.id])

    def test_dry_run_performs_no_writes(self):
        doc = add_document(
            url="https://example.com/dry-run",
            source_name="Bron",
            title="Dry run document",
            full_text="Tekst",
            content_type="html",
        )

        with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc.id), "--dry-run"]):
            exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        with get_session() as session:
            stored = session.query(database.Document).filter(database.Document.id == doc.id).first()
            self.assertIsNone(stored.screening_status)
            self.assertIsNone(stored.screening_input_json)

    def test_doc_id_targets_exactly_one_row(self):
        doc1 = add_document(
            url="https://example.com/one",
            source_name="Bron",
            title="Doc 1",
            full_text="Tekst",
            content_type="html",
        )
        doc2 = add_document(
            url="https://example.com/two",
            source_name="Bron",
            title="Doc 2",
            full_text="Tekst",
            content_type="html",
        )

        fake_result = ScreeningRunResult(
            success=True,
            input_json="{}",
            output=None,
            output_json=json.dumps(
                {
                    "short_summary": "Samenvatting.",
                    "climate_adaptation_relevance_score": 6,
                    "climate_adaptation_explanation": "Toelichting.",
                    "primary_opgave": "klimaatadaptatie",
                    "related_opgaves": [],
                    "related_transities": [],
                    "cross_domain_relevance_signal": "none",
                    "cross_domain_explanation": "none",
                    "confidence": 0.7,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            model="test-model",
        )

        with mock.patch.object(screen_documents, "screen_document", return_value=fake_result):
            with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc2.id)]):
                exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        with get_session() as session:
            stored1 = session.query(database.Document).filter(database.Document.id == doc1.id).first()
            stored2 = session.query(database.Document).filter(database.Document.id == doc2.id).first()
            self.assertIsNone(stored1.screening_status)
            self.assertEqual(stored2.screening_status, "completed")

    def test_failed_run_is_persisted_as_failed(self):
        doc = add_document(
            url="https://example.com/failure",
            source_name="Bron",
            title="Doc fail",
            full_text="Tekst",
            content_type="html",
        )

        fake_result = ScreeningRunResult(
            success=False,
            input_json="{}",
            output=None,
            output_json=None,
            model="test-model",
            error_text="malformed json",
        )

        with mock.patch.object(screen_documents, "screen_document", return_value=fake_result):
            with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc.id)]):
                exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        with get_session() as session:
            stored = session.query(database.Document).filter(database.Document.id == doc.id).first()
            self.assertEqual(stored.screening_status, "failed")
            self.assertEqual(stored.screening_error, "malformed json")


if __name__ == "__main__":
    unittest.main()

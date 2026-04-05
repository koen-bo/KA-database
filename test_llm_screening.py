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
from modules.llm_screening import (
    ExploratoryScreeningRunResult,
    FactualScreeningRunResult,
    screen_document,
)
from modules.screening import (
    FactualActorGroup,
    ExploratoryHypothesis,
    ExploratoryScreeningOutput,
    FactualFoothold,
    FactualRelevanceReason,
    FactualScreeningOutput,
)


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
    testcase._temp_db_path = os.path.join(os.getcwd(), f"test_screening_{uuid.uuid4().hex}.db")
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
            "title": "Versnelling woningbouw botst met hitte en wateroverlast",
            "source_name": "Example",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "html",
            "cleaned_text": (
                "Gemeenten willen tempo maken met woningbouw, maar de analyse laat zien dat hitte, piekbuien "
                "en beperkte ruimte voor groenblauw ontwerp nog onvoldoende in projectkeuzes zijn verankerd."
            ),
            "keyword_tags": json.dumps(["woningbouw", "hitte", "wateroverlast"]),
        }

    def test_two_lane_response_is_accepted(self):
        payloads = [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "factual_summary": "Het document gaat over versnelling van woningbouw onder klimaatdruk.",
                                    "what_is_changing": "Klimaatrisico's moeten eerder in projectkeuzes landen.",
                                    "actors_and_sectors": "Gemeenten, corporaties en bouwsector.",
                                    "actor_groups": [
                                        {"label": "Gemeenten", "role": "Maken ruimtelijke keuzes."},
                                        {"label": "Corporaties en bouwers", "role": "Vertalen eisen naar projecten."},
                                    ],
                                    "opgave_relevance": "Dit raakt huidige keuzes in de gebouwde omgeving.",
                                    "relevance_reasons": [
                                        {"title": "Projectkeuzes", "explanation": "De bron raakt actuele woningbouwbeslissingen."},
                                        {"title": "Uitvoeringslanding", "explanation": "De koppeling met ondersteuning in de gebouwde omgeving is concreet."},
                                    ],
                                    "footholds": [
                                        {"id": "gebouwde_omgeving", "rationale": "Hier landen de projectkeuzes."}
                                    ],
                                    "evidence_quotes": ["Quote 1", "Quote 2"],
                                    "uncertainties": ["Onzeker hoe financiering wordt ingevuld."],
                                    "opgave_signal_score": 8,
                                    "rvo_link_path": "direct_operational",
                                    "score_defense": "De bron raakt direct lopende woningbouwondersteuning en uitvoeringskeuzes.",
                                    "confidence": 0.81,
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "exploration_decision": "analyze",
                                    "decision_rationale": "De factual analyse laat nog lock-invragen open.",
                                    "strategic_memo": "De bron wijst op een lock-in risico als tempo boven robuustheid blijft staan.",
                                    "hypotheses": [
                                        {
                                            "hypothesis": "Tempo drukt adaptatie uit beeld.",
                                            "mechanism": "Versnelling verkleint ruimte voor robuuste ontwerpcriteria.",
                                            "foothold_ids": ["gebouwde_omgeving"],
                                            "evidence_refs": ["quote_1"],
                                            "certainty": "likely",
                                            "verification": "Check gemeentelijke projectcriteria.",
                                        },
                                        {
                                            "hypothesis": "RVO kan standaarden helpen normaliseren.",
                                            "mechanism": "Bestaande ondersteuning kan klimaatrobuuste keuzes eerder verankeren.",
                                            "foothold_ids": ["indicatoren_en_pve"],
                                            "evidence_refs": ["quote_2"],
                                            "certainty": "possible",
                                            "verification": "Vergelijk huidige PvE's met de aanbevelingen in de bron.",
                                        },
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        ]

        def post_func(*args, **kwargs):
            return FakeResponse(payloads.pop(0))

        result = screen_document(self._document(), post_func=post_func)

        self.assertTrue(result.factual.success)
        self.assertIsNotNone(result.factual.output_json)
        self.assertIsNotNone(result.exploratory)
        self.assertTrue(result.exploratory.success)
        self.assertIn("selected_lenses", result.prepared.context_json)

    def test_malformed_factual_json_stops_exploratory(self):
        payload = {"choices": [{"message": {"content": "{not valid json}"}}]}

        result = screen_document(self._document(), post_func=lambda *args, **kwargs: FakeResponse(payload))

        self.assertFalse(result.factual.success)
        self.assertIsNone(result.exploratory)
        self.assertIn("Expecting property name", result.factual.error_text)

    def test_invalid_exploratory_schema_is_reported(self):
        payloads = [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "factual_summary": "Samenvatting.",
                                    "what_is_changing": "Wijziging.",
                                    "actors_and_sectors": "Actoren.",
                                    "actor_groups": [{"label": "Actoren", "role": "Spelen een rol in de uitvoering."}],
                                    "opgave_relevance": "Relevant.",
                                    "relevance_reasons": [{"title": "Relevant", "explanation": "Korte uitleg."}],
                                    "footholds": [{"id": "gebouwde_omgeving", "rationale": "Rationale."}],
                                    "evidence_quotes": ["Quote 1", "Quote 2"],
                                    "uncertainties": [],
                                    "opgave_signal_score": 7,
                                    "rvo_link_path": "mixed",
                                    "score_defense": "Strategisch relevant met een plausibele praktische landing.",
                                    "confidence": 0.8,
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "exploration_decision": "analyze",
                                    "decision_rationale": "Meerwaarde aanwezig.",
                                    "strategic_memo": "Memo",
                                    "hypotheses": [
                                        {
                                            "hypothesis": "Hyp 1",
                                            "mechanism": "Mechanism 1",
                                            "foothold_ids": [],
                                            "evidence_refs": ["quote_1"],
                                            "certainty": "high",
                                            "verification": "Check 1",
                                        },
                                        {
                                            "hypothesis": "Hyp 2",
                                            "mechanism": "Mechanism 2",
                                            "foothold_ids": [],
                                            "evidence_refs": ["quote_2"],
                                            "certainty": "possible",
                                            "verification": "Check 2",
                                        },
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        ]

        def post_func(*args, **kwargs):
            return FakeResponse(payloads.pop(0))

        result = screen_document(self._document(), post_func=post_func)

        self.assertTrue(result.factual.success)
        self.assertIsNotNone(result.exploratory)
        self.assertTrue(result.exploratory.success)
        self.assertEqual(result.exploratory.output.exploration_decision, "not_needed")
        self.assertIn("converted_empty_analyze_to_not_needed", result.exploratory.repairs_applied or [])


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
        doc_new, _, _ = self._create_docs()
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
            self.assertIsNone(stored.screening_exploratory_input_json)

    def test_doc_id_targets_exactly_one_row_and_persists_both_lanes(self):
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

        real_prepared = screen_documents.prepare_document_for_screening(doc2, prompts=config.load_prompts())
        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting.",
            what_is_changing="Wijziging.",
            actors_and_sectors="Actoren.",
            actor_groups=[FactualActorGroup(label="Actoren", role="Spelen een rol in uitvoering.")],
            opgave_relevance="Relevant.",
            relevance_reasons=[FactualRelevanceReason(title="Relevant", explanation="Korte uitleg.")],
            footholds=[FactualFoothold(id="gebouwde_omgeving", rationale="Rationale.")],
            evidence_quotes=["Quote 1", "Quote 2"],
            uncertainties=[],
            opgave_signal_score=6,
            rvo_link_path="mixed",
            score_defense="Strategisch relevant met een plausibele praktische landing.",
            confidence=0.7,
        )
        factual_result = FactualScreeningRunResult(
            success=True,
            input_json=real_prepared.factual_input_json,
            output=factual_output,
            output_json=json.dumps(
                {
                    "factual_summary": factual_output.factual_summary,
                    "what_is_changing": factual_output.what_is_changing,
                    "actors_and_sectors": factual_output.actors_and_sectors,
                    "actor_groups": [{"label": "Actoren", "role": "Spelen een rol in uitvoering."}],
                    "opgave_relevance": factual_output.opgave_relevance,
                    "relevance_reasons": [{"title": "Relevant", "explanation": "Korte uitleg."}],
                    "footholds": [{"id": "gebouwde_omgeving", "rationale": "Rationale."}],
                    "evidence_quotes": factual_output.evidence_quotes,
                    "uncertainties": factual_output.uncertainties,
                    "opgave_signal_score": factual_output.opgave_signal_score,
                    "rvo_link_path": factual_output.rvo_link_path,
                    "score_defense": factual_output.score_defense,
                    "confidence": factual_output.confidence,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            model="test-model",
        )
        exploratory_output = ExploratoryScreeningOutput(
            exploration_decision="analyze",
            decision_rationale="Er is nog strategische meerwaarde.",
            strategic_memo="Memo.",
            hypotheses=[
                ExploratoryHypothesis(
                    hypothesis="Hyp 1",
                    mechanism="Mech 1",
                    foothold_ids=["gebouwde_omgeving"],
                    evidence_refs=["quote_1"],
                    certainty="possible",
                    verification="Check 1",
                ),
                ExploratoryHypothesis(
                    hypothesis="Hyp 2",
                    mechanism="Mech 2",
                    foothold_ids=[],
                    evidence_refs=["quote_2"],
                    certainty="speculative",
                    verification="Check 2",
                ),
            ],
        )
        exploratory_result = ExploratoryScreeningRunResult(
            success=True,
            input_json='{"exploratory":true}',
            output=exploratory_output,
            output_json=json.dumps(
                {
                    "exploration_decision": exploratory_output.exploration_decision,
                    "decision_rationale": exploratory_output.decision_rationale,
                    "strategic_memo": exploratory_output.strategic_memo,
                    "hypotheses": [
                        {
                            "hypothesis": "Hyp 1",
                            "mechanism": "Mech 1",
                            "foothold_ids": ["gebouwde_omgeving"],
                            "evidence_refs": ["quote_1"],
                            "certainty": "possible",
                            "verification": "Check 1",
                        },
                        {
                            "hypothesis": "Hyp 2",
                            "mechanism": "Mech 2",
                            "foothold_ids": [],
                            "evidence_refs": ["quote_2"],
                            "certainty": "speculative",
                            "verification": "Check 2",
                        },
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            model="test-model",
        )

        with mock.patch.object(screen_documents, "prepare_document_for_screening", return_value=real_prepared):
            with mock.patch.object(screen_documents, "screen_factual_document", return_value=factual_result):
                with mock.patch.object(
                    screen_documents,
                    "prepare_exploratory_prompt",
                    return_value=(None, exploratory_result.input_json, "system", "user"),
                ):
                    with mock.patch.object(screen_documents, "screen_exploratory_document", return_value=exploratory_result):
                        with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc2.id)]):
                            exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        with get_session() as session:
            stored1 = session.query(database.Document).filter(database.Document.id == doc1.id).first()
            stored2 = session.query(database.Document).filter(database.Document.id == doc2.id).first()
            self.assertIsNone(stored1.screening_status)
            self.assertEqual(stored2.screening_status, "completed")
            self.assertEqual(stored2.screening_exploratory_status, "completed")
            self.assertEqual(stored2.screening_version, "two_lane_v3_normalized")
            self.assertIsNotNone(stored2.screening_context_json)
            context = json.loads(stored2.screening_context_json)
            self.assertEqual(context.get("factual_output_foothold_ids"), ["gebouwde_omgeving"])
            self.assertEqual(context.get("factual_validation_warnings"), [])
            self.assertEqual(context.get("exploratory_validation_warnings"), [])

    def test_factual_success_and_exploratory_failure_are_persisted(self):
        doc = add_document(
            url="https://example.com/failure",
            source_name="Bron",
            title="Doc fail",
            full_text="Tekst",
            content_type="html",
        )

        real_prepared = screen_documents.prepare_document_for_screening(doc, prompts=config.load_prompts())
        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting.",
            what_is_changing="Wijziging.",
            actors_and_sectors="Actoren.",
            actor_groups=[FactualActorGroup(label="Actoren", role="Spelen een rol in uitvoering.")],
            opgave_relevance="Relevant.",
            relevance_reasons=[FactualRelevanceReason(title="Relevant", explanation="Korte uitleg.")],
            footholds=[FactualFoothold(id="gebouwde_omgeving", rationale="Rationale.")],
            evidence_quotes=["Quote 1", "Quote 2"],
            uncertainties=[],
            opgave_signal_score=6,
            rvo_link_path="mixed",
            score_defense="Strategisch relevant met een plausibele praktische landing.",
            confidence=0.7,
        )
        factual_result = FactualScreeningRunResult(
            success=True,
            input_json=real_prepared.factual_input_json,
            output=factual_output,
            output_json=json.dumps(
                {
                    "factual_summary": factual_output.factual_summary,
                    "what_is_changing": factual_output.what_is_changing,
                    "actors_and_sectors": factual_output.actors_and_sectors,
                    "actor_groups": [{"label": "Actoren", "role": "Spelen een rol in uitvoering."}],
                    "opgave_relevance": factual_output.opgave_relevance,
                    "relevance_reasons": [{"title": "Relevant", "explanation": "Korte uitleg."}],
                    "footholds": [{"id": "gebouwde_omgeving", "rationale": "Rationale."}],
                    "evidence_quotes": factual_output.evidence_quotes,
                    "uncertainties": factual_output.uncertainties,
                    "opgave_signal_score": factual_output.opgave_signal_score,
                    "rvo_link_path": factual_output.rvo_link_path,
                    "score_defense": factual_output.score_defense,
                    "confidence": factual_output.confidence,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            model="test-model",
        )
        exploratory_result = ExploratoryScreeningRunResult(
            success=False,
            input_json='{"exploratory":true}',
            output=None,
            output_json=None,
            model="test-model",
            error_text="bad exploratory json",
        )

        with mock.patch.object(screen_documents, "prepare_document_for_screening", return_value=real_prepared):
            with mock.patch.object(screen_documents, "screen_factual_document", return_value=factual_result):
                with mock.patch.object(
                    screen_documents,
                    "prepare_exploratory_prompt",
                    return_value=(None, exploratory_result.input_json, "system", "user"),
                ):
                    with mock.patch.object(screen_documents, "screen_exploratory_document", return_value=exploratory_result):
                        with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc.id), "--force-rescreen"]):
                            exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        with get_session() as session:
            stored = session.query(database.Document).filter(database.Document.id == doc.id).first()
            self.assertEqual(stored.screening_status, "completed")
            self.assertEqual(stored.screening_exploratory_status, "failed")
            self.assertEqual(stored.screening_exploratory_error, "bad exploratory json")
            self.assertIsNone(stored.screening_exploratory_output_json)

    def test_factual_failure_skips_exploratory(self):
        doc = add_document(
            url="https://example.com/factual-failure",
            source_name="Bron",
            title="Doc factual fail",
            full_text="Tekst",
            content_type="html",
        )
        mark_document_screening_completed(doc.id, "{}", '{"old":"value"}', "old-model")

        real_prepared = screen_documents.prepare_document_for_screening(doc, prompts=config.load_prompts())
        factual_result = FactualScreeningRunResult(
            success=False,
            input_json=real_prepared.factual_input_json,
            output=None,
            output_json=None,
            model="test-model",
            error_text="bad factual json",
        )

        with mock.patch.object(screen_documents, "prepare_document_for_screening", return_value=real_prepared):
            with mock.patch.object(screen_documents, "screen_factual_document", return_value=factual_result):
                with mock.patch.object(screen_documents, "screen_exploratory_document") as exploratory_mock:
                    with mock.patch.object(sys, "argv", ["screen_documents.py", "--doc-id", str(doc.id), "--force-rescreen"]):
                        exit_code = screen_documents.main()

        self.assertEqual(exit_code, 0)
        self.assertFalse(exploratory_mock.called)
        with get_session() as session:
            stored = session.query(database.Document).filter(database.Document.id == doc.id).first()
            self.assertEqual(stored.screening_status, "failed")
            self.assertIsNone(stored.screening_output_json)
            self.assertIsNone(stored.screening_exploratory_status)


if __name__ == "__main__":
    unittest.main()

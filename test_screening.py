import json
import os
import tempfile
import unittest
from datetime import datetime

from modules.screening import (
    PDF_EXTRACT_DELIMITER,
    FactualActorGroup,
    FactualRelevanceReason,
    FactualScreeningOutput,
    build_exploratory_llm_screening_request,
    build_exploratory_screening_user_message,
    build_llm_screening_request,
    build_screening_input,
    build_screening_user_message,
    clean_document_text,
    compile_exploratory_system_prompt,
    compile_factual_system_prompt,
    count_words,
    exploratory_screening_output_schema,
    extract_cleaned_paragraphs,
    factual_screening_output_schema,
    find_heading_like_paragraphs,
    normalize_exploratory_screening_output,
    normalize_factual_screening_output,
    parse_raw_exploratory_screening_output,
    parse_raw_factual_screening_output,
    serialize_exploratory_llm_screening_request,
    serialize_llm_screening_request,
    serialize_screening_input,
    split_cleaned_sections,
    validate_exploratory_screening_output,
    validate_factual_screening_output,
)
from modules.screening_context import (
    load_core_context,
    load_regression_fixtures,
    load_rvo_footholds,
    load_strategic_lenses,
    select_context_for_document,
)
from modules.screening_storage import (
    parse_exploratory_screening_output,
    parse_factual_screening_output,
    parse_screening_context,
)


class ScreeningCleanupTests(unittest.TestCase):
    def test_html_cleanup_removes_top_noise_and_duplicate_title(self):
        raw_text = (
            "Klimaatadaptatie in de gebouwde omgeving\n\n"
            "Klimaatadaptatie in de gebouwde omgeving\n\n"
            "Nieuwsbericht | 13-06-2024 | 10:10\n\n"
            "Lees voor\n\n"
            "Dit is de eerste inhoudelijke paragraaf met voldoende context en lengte voor screening gebruik.\n\n"
            "Dit is de tweede inhoudelijke paragraaf die ook gewoon behouden moet blijven."
        )

        result = clean_document_text(raw_text, content_type="html")

        self.assertNotIn("Nieuwsbericht | 13-06-2024 | 10:10", result.cleaned_text)
        self.assertNotIn("Lees voor", result.cleaned_text)
        self.assertEqual(result.cleaned_text.count("Klimaatadaptatie in de gebouwde omgeving"), 1)

    def test_pdf_cleanup_splits_heading_prefixed_summary_paragraph(self):
        raw_text = (
            "Samenvatting Deze paragraaf beschrijft de hoofdboodschap van het rapport en geeft "
            "voldoende context voor de screening van lange pdf-documenten in deze pipeline."
        )

        result = clean_document_text(raw_text, content_type="pdf")
        paragraphs = extract_cleaned_paragraphs(result.cleaned_text)

        self.assertEqual(paragraphs[0], "Samenvatting")
        self.assertIn("hoofdboodschap van het rapport", paragraphs[1])

    def test_merged_cleanup_preserves_delimiter_and_sections(self):
        raw_text = (
            "Artikel titel\n\n"
            "Nieuwsbericht | 13-06-2024 | 10:10\n\n"
            "Dit is de artikeltekst met voldoende lengte voor later gebruik.\n\n"
            f"{PDF_EXTRACT_DELIMITER}\n\n"
            "Header rapport\n"
            "1\n"
            "Relevante pdf paragraaf over watergebruik in de industrie."
        )

        result = clean_document_text(raw_text, content_type="html")
        article_text, pdf_text = split_cleaned_sections(result.cleaned_text)

        self.assertIn(PDF_EXTRACT_DELIMITER, result.cleaned_text)
        self.assertNotIn("Nieuwsbericht | 13-06-2024 | 10:10", article_text)
        self.assertIsNotNone(pdf_text)
        self.assertIn("watergebruik in de industrie", pdf_text)


class ScreeningPayloadTests(unittest.TestCase):
    def test_html_payload_uses_lead_paragraphs_only(self):
        document = {
            "id": 1,
            "url": "https://example.com/a",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": datetime(2025, 1, 2, 10, 0, 0),
            "discovery_method": "listing",
            "content_type": "html",
            "cleaned_text": (
                "Titel\n\n"
                "Deze eerste inhoudelijke paragraaf bevat ruim voldoende tekst om als eerste excerpt-paragraaf te dienen voor screening.\n\n"
                "Deze tweede paragraaf bevat aanvullende informatie over klimaatadaptatie en stedelijke hitteproblematiek voor RVO.\n\n"
                "Deze derde paragraaf bevat context over wateroverlast en gebiedsontwikkeling in de gebouwde omgeving."
            ),
            "keyword_tags": json.dumps(["klimaatadaptatie", "hitte"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "html_lead")
        self.assertLessEqual(count_words(payload.excerpt_text), 1500)
        self.assertEqual(payload.publication_date, "2025-01-02")

    def test_html_with_pdf_payload_includes_pdf_when_keyword_signal_exists(self):
        document = {
            "id": 2,
            "url": "https://example.com/b",
            "title": "Industrie en water",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "sitemap",
            "content_type": "html",
            "cleaned_text": (
                "Korte artikelparagraaf met enige context maar niet heel veel detail.\n\n"
                f"{PDF_EXTRACT_DELIMITER}\n\n"
                "Samenvatting\n\n"
                "Deze pdf paragraaf benoemt klimaatadaptatie en watergebruik in de industrie als gekoppelde opgave voor beleid. "
                "De samenvatting maakt duidelijk waarom dit document relevant is voor screening.\n\n"
                "Nog een pdf paragraaf over droogte en industrieel watergebruik met voldoende context."
            ),
            "keyword_tags": json.dumps(["watergebruik", "klimaatadaptatie"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "html_lead_plus_pdf_summary_section")
        self.assertIn("PDF_EXCERPT:", payload.excerpt_text)
        self.assertTrue(payload.has_linked_pdf)

    def test_pdf_payload_prefers_heading_then_keyword_hit_paragraphs(self):
        document = {
            "id": 3,
            "url": "https://example.com/c",
            "title": "Waterrapport",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "pdf",
            "cleaned_text": (
                "Algemene inleiding met voldoende tekst maar zonder relevante trefwoorden.\n\n"
                "Samenvatting\n\n"
                "Deze samenvattende paragraaf beschrijft de hoofdboodschap van het rapport en geeft voldoende context voor screening.\n\n"
                "Conclusies\n\n"
                "Deze paragraaf gaat over klimaatadaptatie, watergebruik en industrie en hoort daarom geselecteerd te worden."
            ),
            "keyword_tags": json.dumps(["watergebruik", "klimaatadaptatie"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "pdf_heading_plus_keyword")
        self.assertIn("hoofdboodschap van het rapport", payload.excerpt_text)
        self.assertIn("watergebruik", payload.excerpt_text)

    def test_payload_serialization_is_stable_json(self):
        document = {
            "id": 5,
            "url": "https://example.com/e",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "html",
            "cleaned_text": "Een lange paragraaf met genoeg woorden voor excerpt selectie in de screening payload builder.",
            "keyword_tags": json.dumps(["klimaatadaptatie"]),
        }

        payload = build_screening_input(document)
        self.assertEqual(serialize_screening_input(payload), serialize_screening_input(payload))

    def test_find_heading_like_paragraphs_recognizes_canonical_headings(self):
        paragraphs = ["Voorwoord", "Samenvatting", "Gewone tekst", "Conclusies:", "Aanbevelingen"]
        indexes = find_heading_like_paragraphs(paragraphs)
        self.assertEqual(indexes, [1, 3, 4])


class ScreeningContextTests(unittest.TestCase):
    def test_context_assets_load(self):
        self.assertTrue(load_core_context())
        self.assertEqual(len(load_strategic_lenses()), 10)
        self.assertEqual(len(load_rvo_footholds()), 15)
        self.assertGreaterEqual(len(load_regression_fixtures()), 8)

    def test_zero_score_items_are_not_selected(self):
        selection = select_context_for_document(
            title="Algemeen economisch bericht",
            keyword_tags=["macro", "markt"],
            excerpt_text="Dit document gaat over export, omzet en arbeidsmarkt zonder fysieke of ruimtelijke beleidskoppelingen.",
        )

        self.assertEqual(selection.selected_lenses, [])
        self.assertEqual(selection.selected_footholds, [])
        self.assertTrue(selection.selection_metadata["factual_lenses_truncated_by_fit"])

    def test_weighted_zone_matching_prefers_title_then_tags_then_excerpt(self):
        custom_lens = [
            {
                "id": "custom_water",
                "title": "Custom water lens",
                "core_question": "Vraag",
                "signals_to_notice": [],
                "why_it_matters": "Waarom",
                "runtime_guidance": "Guidance",
                "selection_terms": ["water"],
                "boost_terms": [],
                "exclude_terms": [],
            }
        ]
        selection = select_context_for_document(
            title="Water als randvoorwaarde",
            keyword_tags=["water"],
            excerpt_text="Water blijft hier ook in het excerpt terugkomen.",
            lenses=custom_lens,
            footholds=[],
        )

        self.assertEqual(len(selection.selected_lenses), 1)
        ranked = selection.selected_lenses[0]
        self.assertEqual(ranked.score, 7)
        self.assertEqual(ranked.matched_zones["title"], 1)
        self.assertEqual(ranked.matched_zones["keyword_tags"], 1)
        self.assertEqual(ranked.matched_zones["excerpt_text"], 1)

    def test_exclude_terms_can_suppress_false_positive_context(self):
        custom_footholds = [
            {
                "id": "custom_industrie",
                "title": "Custom industrie foothold",
                "description": "Desc",
                "leverage": "Lev",
                "typical_triggers": [],
                "runtime_guidance": "Guidance",
                "selection_terms": ["industrie"],
                "boost_terms": [],
                "exclude_terms": ["emissiereductie"],
            }
        ]
        selection = select_context_for_document(
            title="Industriebeleid en emissiereductie",
            keyword_tags=["industrie", "emissiereductie"],
            excerpt_text="Het document gaat over emissiereductie en concurrentiekracht, niet over water of adaptatie.",
            lenses=[],
            footholds=custom_footholds,
        )

        self.assertEqual(selection.selected_footholds, [])

    def test_invalid_context_asset_raises(self):
        broken_path = os.path.join(os.getcwd(), "broken_screening_context_test.json")
        try:
            with open(broken_path, "w", encoding="utf-8") as f:
                json.dump([{"id": "broken", "title": "Broken"}], f)

            with self.assertRaises(ValueError):
                load_strategic_lenses(filepath=broken_path)
        finally:
            if os.path.exists(broken_path):
                os.remove(broken_path)

    def test_agriculture_fixture_selects_expected_context(self):
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_agrarische_droogte")
        selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

        self.assertIn("agrarische_klanten_instrumentmix", [item.id for item in selection.selected_footholds])
        self.assertIn("gebiedsprocessen_hefboom", [item.id for item in selection.selected_lenses])

    def test_housing_fixture_selects_expected_context(self):
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_woningbouw_hitte")
        selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

        self.assertIn("versnelling_vs_toekomstbestendigheid", [item.id for item in selection.selected_lenses])
        self.assertIn("gebouwde_omgeving", [item.id for item in selection.selected_footholds])

    def test_energy_fixture_selects_expected_context(self):
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_miek_lockin")
        selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

        self.assertIn("lockins_lange_levensduur", [item.id for item in selection.selected_lenses])
        self.assertIn("miek_energie_infra", [item.id for item in selection.selected_footholds])

    def test_industry_fixture_selects_expected_context(self):
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_industrie_water")
        selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

        self.assertIn("verdienvermogen_en_industrie", [item.id for item in selection.selected_lenses])
        self.assertIn("industrie_waterweerbaarheid", [item.id for item in selection.selected_footholds])

    def test_indirect_signal_fixture_selects_expected_context(self):
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_indirect_signaal")
        selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

        self.assertIn("versnelling_vs_toekomstbestendigheid", [item.id for item in selection.selected_lenses])
        self.assertIn("gebouwde_omgeving", [item.id for item in selection.selected_footholds])


class ScreeningPromptTests(unittest.TestCase):
    def setUp(self):
        self.prompts = {
            "factual_system_intro": "FACTUAL INTRO",
            "factual_task_instructions": "FACTUAL TASK",
            "factual_output_contract": "FACTUAL CONTRACT",
            "exploratory_system_intro": "EXPLORATORY INTRO",
            "exploratory_task_instructions": "EXPLORATORY TASK",
            "exploratory_output_contract": "EXPLORATORY CONTRACT",
        }
        fixture = next(item for item in load_regression_fixtures() if item["id"] == "fixture_woningbouw_hitte")
        self.selection = select_context_for_document(
            title=fixture["title"],
            keyword_tags=fixture["keyword_tags"],
            excerpt_text=fixture["excerpt_text"],
        )

    def test_compile_factual_prompt_includes_context(self):
        compiled = compile_factual_system_prompt(
            self.prompts,
            selected_lenses=self.selection.selected_lenses,
            selected_footholds=self.selection.selected_footholds,
            core_context_text="CORE CONTEXT",
        )

        self.assertIn("FACTUAL INTRO", compiled)
        self.assertIn("CORE CONTEXT", compiled)
        self.assertIn(self.selection.selected_lenses[0].title, compiled)
        self.assertIn(self.selection.selected_footholds[0].title, compiled)

    def test_compile_exploratory_prompt_includes_context(self):
        compiled = compile_exploratory_system_prompt(
            self.prompts,
            selected_lenses=self.selection.exploratory_lenses,
            selected_footholds=self.selection.exploratory_footholds,
            core_context_text="CORE CONTEXT",
        )

        self.assertIn("EXPLORATORY INTRO", compiled)
        self.assertIn("EXPLORATORY CONTRACT", compiled)
        self.assertIn(self.selection.exploratory_lenses[0].title, compiled)

    def test_request_builders_wrap_json(self):
        document = {
            "id": 9,
            "url": "https://example.com/i",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": datetime(2025, 5, 6, 9, 30, 0),
            "discovery_method": "listing",
            "content_type": "html",
            "cleaned_text": "Deze paragraaf bevat voldoende inhoud om in de excerpt terecht te komen.",
            "keyword_tags": json.dumps(["klimaatadaptatie", "watergebruik"]),
        }

        payload = build_screening_input(document)
        factual_request = build_llm_screening_request(payload)
        factual_json = json.loads(serialize_llm_screening_request(factual_request))
        self.assertEqual(
            sorted(factual_json.keys()),
            ["excerpt_text", "keyword_tags", "publication_date", "source_name", "title"],
        )
        self.assertTrue(build_screening_user_message(factual_request).startswith("SCREENING_INPUT_JSON:\n{"))

        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting",
            what_is_changing="Er verandert iets",
            actors_and_sectors="Gemeenten en corporaties",
            actor_groups=[
                FactualActorGroup(label="Gemeenten", role="Maken ruimtelijke keuzes."),
            ],
            opgave_relevance="Relevantie",
            relevance_reasons=[
                FactualRelevanceReason(title="Ruimtelijke keuze", explanation="Klimaatrisico's landen in lopende projecten."),
            ],
            footholds=[],
            evidence_quotes=["Quote 1", "Quote 2"],
            uncertainties=[],
            opgave_signal_score=7,
            rvo_link_path="mixed",
            score_defense="De score volgt uit strategische relevantie en een plausibele uitvoeringslanding.",
            confidence=0.8,
        )
        exploratory_request = build_exploratory_llm_screening_request(payload, factual_output)
        exploratory_json = json.loads(serialize_exploratory_llm_screening_request(exploratory_request))
        self.assertIn("factual_analysis", exploratory_json)
        self.assertTrue(
            build_exploratory_screening_user_message(exploratory_request).startswith(
                "EXPLORATORY_SCREENING_INPUT_JSON:\n{"
            )
        )


class ScreeningOutputValidationTests(unittest.TestCase):
    def test_validate_factual_output_accepts_valid_schema(self):
        output = validate_factual_screening_output(
            {
                "factual_summary": "Bron over woningbouw en hitte.",
                "what_is_changing": "Tempo in woningbouw komt onder druk door klimaatrisico's.",
                "actors_and_sectors": "Gemeenten, corporaties en bouwsector.",
                "actor_groups": [
                    {"label": "Gemeenten", "role": "Maken ruimtelijke keuzes."},
                    {"label": "Corporaties", "role": "Beheren en ontwikkelen woningvoorraad."},
                ],
                "opgave_relevance": "Dit raakt keuzes van nu in de gebouwde omgeving.",
                "relevance_reasons": [
                    {"title": "Lopende projecten", "explanation": "De bron raakt keuzes die nu worden gemaakt."},
                    {"title": "RVO-landing", "explanation": "Er is een duidelijke koppeling met woningbouwondersteuning."},
                ],
                "footholds": [
                    {"id": "gebouwde_omgeving", "rationale": "Hier landen de projectkeuzes."},
                    {"id": "expertteam_woningbouw", "rationale": "Hier kan kwaliteitsborging meekomen."}
                ],
                "evidence_quotes": ["Quote 1", "Quote 2"],
                "uncertainties": ["Onzeker of financiering al geregeld is."],
                "opgave_signal_score": 8,
                "rvo_link_path": "direct_operational",
                "score_defense": "De bron heeft een duidelijke RVO-landing in lopende woningbouwondersteuning.",
                "confidence": 0.82,
            }
        )

        self.assertEqual(output.opgave_signal_score, 8)
        self.assertEqual(output.footholds[0].id, "gebouwde_omgeving")
        self.assertEqual(output.rvo_link_path, "direct_operational")
        self.assertEqual(output.actor_groups[0].label, "Gemeenten")
        self.assertEqual(output.relevance_reasons[0].title, "Lopende projecten")

    def test_validate_factual_output_allows_empty_footholds(self):
        output = validate_factual_screening_output(
            {
                "factual_summary": "Samenvatting",
                "what_is_changing": "Wijziging",
                "actors_and_sectors": "Actoren",
                "opgave_relevance": "Relevantie",
                "footholds": [],
                "evidence_quotes": ["Quote 1", "Quote 2"],
                "uncertainties": [],
                "opgave_signal_score": 5,
                "rvo_link_path": "strategic_indirect",
                "score_defense": "De bron is strategisch relevant zonder concrete RVO-landing in de tekst.",
                "confidence": 0.7,
            }
        )
        self.assertEqual(output.footholds, [])

    def test_normalize_factual_output_drops_unknown_foothold(self):
        normalized = normalize_factual_screening_output(
            parse_raw_factual_screening_output(
                {
                    "factual_summary": "Samenvatting",
                    "what_is_changing": "Wijziging",
                    "actors_and_sectors": "Actoren",
                    "opgave_relevance": "Relevantie",
                    "footholds": [{"id": "onbekend", "rationale": "Rationale"}],
                    "evidence_quotes": ["Quote 1", "Quote 2"],
                    "uncertainties": [],
                    "opgave_signal_score": 5,
                    "rvo_link_path": "weak",
                    "score_defense": "De bron heeft geen duidelijke landing.",
                    "confidence": 0.7,
                }
            )
        )
        self.assertEqual(normalized.output.footholds, [])
        self.assertIn("dropped_invalid_factual_foothold_id", normalized.repairs_applied)

    def test_normalize_factual_output_derives_missing_score_fields(self):
        normalized = normalize_factual_screening_output(
            parse_raw_factual_screening_output(
                {
                    "factual_summary": "Samenvatting",
                    "what_is_changing": "Wijziging",
                    "actors_and_sectors": "Actoren",
                    "opgave_relevance": "Relevantie",
                    "footholds": [],
                    "evidence_quotes": ["Quote 1", "Quote 2"],
                    "uncertainties": [],
                    "opgave_signal_score": 6,
                    "confidence": 0.7,
                }
            )
        )
        self.assertTrue(normalized.output.rvo_link_path)
        self.assertTrue(normalized.output.score_defense)
        self.assertIn("derived_rvo_link_path", normalized.repairs_applied)
        self.assertIn("derived_score_defense", normalized.repairs_applied)

    def test_validate_exploratory_output_accepts_valid_schema(self):
        output = validate_exploratory_screening_output(
            {
                "exploration_decision": "analyze",
                "decision_rationale": "De factual analyse laat nog open strategische vragen zien.",
                "strategic_memo": "Dit document kan een lock-in zichtbaar maken.",
                "hypotheses": [
                    {
                        "hypothesis": "Tempo drukt adaptatie uit beeld.",
                        "mechanism": "Versnelling verlaagt aandacht voor ruimtelijke randvoorwaarden.",
                        "foothold_ids": ["gebouwde_omgeving"],
                        "evidence_refs": ["quote_1"],
                        "certainty": "likely",
                        "verification": "Check projectcriteria en gemeentelijke PvE's.",
                    },
                    {
                        "hypothesis": "RVO kan standaarden helpen normaliseren.",
                        "mechanism": "Bestaande ondersteuning kan adaptatie-eisen earlier meenemen.",
                        "foothold_ids": ["indicatoren_en_pve"],
                        "evidence_refs": ["quote_2"],
                        "certainty": "possible",
                        "verification": "Vergelijk huidige standaarden met de documentaanbevelingen.",
                    },
                ],
            },
            allowed_evidence_refs={"quote_1", "quote_2"},
        )

        self.assertEqual(len(output.hypotheses), 2)
        self.assertEqual(output.hypotheses[0].certainty, "likely")
        self.assertEqual(output.exploration_decision, "analyze")

    def test_validate_exploratory_output_accepts_not_needed(self):
        output = validate_exploratory_screening_output(
            {
                "exploration_decision": "not_needed",
                "decision_rationale": "Het document voegt strategisch weinig toe boven de factual analyse.",
                "strategic_memo": "De factual analyse is voor dit stuk voldoende.",
                "hypotheses": [],
            },
            allowed_evidence_refs={"quote_1", "quote_2"},
        )
        self.assertEqual(output.exploration_decision, "not_needed")
        self.assertEqual(output.hypotheses, [])

    def test_normalize_exploratory_output_repairs_invalid_certainty(self):
        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting",
            what_is_changing="Wijziging",
            actors_and_sectors="Gemeenten en bouwsector",
            actor_groups=[],
            opgave_relevance="Dit raakt woningbouw en ontwerpkeuzes.",
            relevance_reasons=[],
            footholds=[],
            evidence_quotes=["woningbouw en hitte", "ontwerpkeuzes en adaptatie"],
            uncertainties=[],
            opgave_signal_score=7,
            rvo_link_path="mixed",
            score_defense="Plausibele RVO-landing.",
            confidence=0.8,
        )
        normalized = normalize_exploratory_screening_output(
            parse_raw_exploratory_screening_output(
                {
                    "exploration_decision": "analyze",
                    "decision_rationale": "Meerwaarde aanwezig.",
                    "strategic_memo": "Memo",
                    "hypotheses": [
                        {
                            "hypothesis": "Hypothese 1 over woningbouw",
                            "mechanism": "Mechanism 1 over hitte en ontwerpkeuzes",
                            "foothold_ids": [],
                            "evidence_refs": ["quote_1"],
                            "certainty": "high",
                            "verification": "Stap 1",
                        }
                    ],
                }
            ),
            factual_output=factual_output,
        )
        self.assertEqual(normalized.output.hypotheses[0].certainty, "possible")
        self.assertIn("replaced_invalid_certainty", normalized.repairs_applied)

    def test_normalize_exploratory_output_derives_missing_evidence_refs(self):
        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting",
            what_is_changing="Wijziging",
            actors_and_sectors="Gemeenten en bouwsector",
            actor_groups=[],
            opgave_relevance="Dit raakt woningbouw en hitte in de gebouwde omgeving.",
            relevance_reasons=[],
            footholds=[],
            evidence_quotes=["woningbouw en hitte", "groenblauw ontwerp in wijken"],
            uncertainties=[],
            opgave_signal_score=7,
            rvo_link_path="mixed",
            score_defense="Plausibele RVO-landing.",
            confidence=0.8,
        )
        normalized = normalize_exploratory_screening_output(
            parse_raw_exploratory_screening_output(
                {
                    "exploration_decision": "analyze",
                    "decision_rationale": "Meerwaarde aanwezig.",
                    "strategic_memo": "Memo",
                    "hypotheses": [
                        {
                            "hypothesis": "Hypothese over woningbouw en hitte",
                            "mechanism": "Mechanism over groenblauw ontwerp",
                            "foothold_ids": ["gebouwde_omgeving"],
                            "certainty": "possible",
                            "verification": "Stap 1",
                        }
                    ],
                }
            ),
            factual_output=factual_output,
        )
        self.assertEqual(normalized.output.hypotheses[0].evidence_refs, ["quote_1", "quote_2"])
        self.assertIn("derived_evidence_refs", normalized.repairs_applied)

    def test_normalize_exploratory_output_caps_weak_cases(self):
        factual_output = FactualScreeningOutput(
            factual_summary="Samenvatting",
            what_is_changing="Wijziging",
            actors_and_sectors="Actoren",
            actor_groups=[],
            opgave_relevance="Relevantie",
            relevance_reasons=[],
            footholds=[],
            evidence_quotes=["algemene relevantie", "beperkte koppeling"],
            uncertainties=[],
            opgave_signal_score=4,
            rvo_link_path="weak",
            score_defense="Zwakke RVO-link.",
            confidence=0.6,
        )
        normalized = normalize_exploratory_screening_output(
            parse_raw_exploratory_screening_output(
                {
                    "exploration_decision": "analyze",
                    "decision_rationale": "Meerwaarde aanwezig.",
                    "strategic_memo": "Memo",
                    "hypotheses": [
                        {
                            "hypothesis": "Algemene hypothese",
                            "mechanism": "Algemeen mechanisme",
                            "foothold_ids": ["gebouwde_omgeving"],
                            "evidence_refs": ["quote_1"],
                            "certainty": "possible",
                            "verification": "Stap 1",
                        }
                    ],
                }
            ),
            factual_output=factual_output,
        )
        self.assertEqual(normalized.output.exploration_decision, "not_needed")
        self.assertEqual(normalized.output.hypotheses, [])

    def test_schema_helpers_reflect_new_contracts(self):
        factual_schema = factual_screening_output_schema()
        exploratory_schema = exploratory_screening_output_schema()

        self.assertIn("factual_summary", factual_schema)
        self.assertNotIn("short_summary", factual_schema)
        self.assertIn("rvo_link_path", factual_schema)
        self.assertIn("actor_groups", factual_schema)
        self.assertIn("relevance_reasons", factual_schema)
        self.assertIn("strategic_memo", exploratory_schema)
        self.assertIn("exploration_decision", exploratory_schema)
        self.assertIn("hypotheses", exploratory_schema)


class ScreeningStorageParsingTests(unittest.TestCase):
    def test_parse_new_factual_output(self):
        raw = json.dumps(
            {
                "factual_summary": "Samenvatting",
                "what_is_changing": "Wijziging",
                "actors_and_sectors": "Actoren",
                "actor_groups": [{"label": "Actoren", "role": "Spelen een rol in de uitvoering."}],
                "opgave_relevance": "Relevantie",
                "relevance_reasons": [{"title": "Relevant", "explanation": "Korte uitleg."}],
                "footholds": [{"id": "gebouwde_omgeving", "rationale": "r"}],
                "evidence_quotes": ["Q1", "Q2"],
                "uncertainties": [],
                "opgave_signal_score": 7,
                "rvo_link_path": "mixed",
                "score_defense": "De score is gebaseerd op een plausibele, maar niet volledig directe, RVO-link.",
                "confidence": 0.8,
            }
        )
        parsed = parse_factual_screening_output(raw)
        self.assertEqual(parsed["opgave_signal_score"], 7)
        self.assertEqual(parsed["rvo_link_path"], "mixed")
        self.assertEqual(parsed["actor_groups"][0]["label"], "Actoren")
        self.assertEqual(parsed["relevance_reasons"][0]["title"], "Relevant")

    def test_parse_legacy_factual_output_maps_fields(self):
        raw = json.dumps(
            {
                "short_summary": "Legacy summary",
                "climate_adaptation_relevance_score": 6,
                "climate_adaptation_explanation": "Legacy explanation",
                "confidence": 0.6,
            }
        )
        parsed = parse_factual_screening_output(raw)
        self.assertEqual(parsed["factual_summary"], "Legacy summary")
        self.assertEqual(parsed["opgave_signal_score"], 6)
        self.assertTrue(parsed["_legacy"])
        self.assertEqual(parsed["actor_groups"], [])
        self.assertEqual(parsed["relevance_reasons"], [])

    def test_parse_exploratory_output(self):
        raw = json.dumps(
            {
                "exploration_decision": "analyze",
                "decision_rationale": "Er zijn nog relevante hypotheses mogelijk.",
                "strategic_memo": "Memo",
                "hypotheses": [
                    {
                        "hypothesis": "Hyp 1",
                        "mechanism": "Mech 1",
                        "foothold_ids": [],
                        "evidence_refs": ["quote_1"],
                        "certainty": "possible",
                        "verification": "Verif 1",
                    },
                    {
                        "hypothesis": "Hyp 2",
                        "mechanism": "Mech 2",
                        "foothold_ids": [],
                        "evidence_refs": ["quote_2"],
                        "certainty": "speculative",
                        "verification": "Verif 2",
                    },
                ],
            }
        )
        self.assertEqual(parse_exploratory_screening_output(raw)["strategic_memo"], "Memo")

    def test_parse_screening_context(self):
        raw = json.dumps(
            {
                "core_context_version": "v1",
                "selected_lenses": [{"id": "a", "title": "A", "score": 1, "matched_terms": ["x"], "matched_zones": {"title": 1}}],
                "selected_footholds": [],
                "exploratory_lenses": [],
                "exploratory_footholds": [],
                "selection_metadata": {"minimum_score": 1},
            }
        )
        self.assertEqual(parse_screening_context(raw)["core_context_version"], "v1")


if __name__ == "__main__":
    unittest.main()

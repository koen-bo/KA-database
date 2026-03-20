import json
import unittest
from datetime import datetime

from modules.screening import (
    PDF_EXTRACT_DELIMITER,
    build_llm_screening_request,
    build_screening_input,
    build_screening_user_message,
    clean_document_text,
    compile_screening_system_prompt,
    count_words,
    extract_cleaned_paragraphs,
    find_heading_like_paragraphs,
    paragraph_keyword_score,
    screening_output_schema,
    serialize_screening_input,
    serialize_llm_screening_request,
    split_cleaned_sections,
    validate_screening_output,
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
        self.assertEqual(
            result.cleaned_text.count("Klimaatadaptatie in de gebouwde omgeving"),
            1,
        )

    def test_pdf_cleanup_removes_repeated_headers_toc_and_page_numbers(self):
        raw_text = (
            "Waterrapport 2025\n"
            "1\n"
            "Inhoudsopgave ..... 2\n"
            "\n"
            "Waterrapport 2025\n"
            "2\n"
            "Deze paragraaf beschrijft hoe droogte en waterbeschikbaarheid de industrie raken in Nederland.\n"
            "De tekst loopt door op een tweede regel zonder echte paragraafbreuk.\n"
            "\n"
            "Waterrapport 2025\n"
            "3\n"
            "Een tweede inhoudelijke paragraaf met genoeg woorden en context voor selectie later."
        )

        result = clean_document_text(raw_text, content_type="pdf")

        self.assertNotIn("Inhoudsopgave ..... 2", result.cleaned_text)
        self.assertNotIn("\n1\n", result.cleaned_text)
        self.assertNotIn("Waterrapport 2025\n\nWaterrapport 2025", result.cleaned_text)
        self.assertIn("droogte en waterbeschikbaarheid", result.cleaned_text)

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

    def test_extract_cleaned_paragraphs_returns_stable_split(self):
        cleaned = "Paragraaf een.\n\nParagraaf twee.\n\nParagraaf drie."
        self.assertEqual(
            extract_cleaned_paragraphs(cleaned),
            ["Paragraaf een.", "Paragraaf twee.", "Paragraaf drie."],
        )

    def test_html_cleanup_preserves_multiple_block_paragraphs(self):
        raw_text = (
            "Titel van artikel\n"
            "Nieuwsbericht | 13-06-2024 | 10:10\n"
            "Dit is de eerste inhoudelijke HTML-paragraaf met genoeg tekst om zelfstandig te blijven staan.\n"
            "Dit is de tweede inhoudelijke HTML-paragraaf met voldoende context over water en klimaatadaptatie.\n"
            "Dit is de derde inhoudelijke HTML-paragraaf die ook niet samengevoegd moet worden."
        )

        result = clean_document_text(raw_text, content_type="html")
        paragraphs = extract_cleaned_paragraphs(result.cleaned_text)

        self.assertGreaterEqual(len(paragraphs), 3)
        self.assertTrue(paragraphs[0].startswith("Titel van artikel"))
        self.assertTrue(paragraphs[1].startswith("Dit is de eerste inhoudelijke HTML-paragraaf"))


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
                "Deze derde paragraaf bevat context over wateroverlast en gebiedsontwikkeling in de gebouwde omgeving.\n\n"
                "Deze vierde paragraaf blijft ook beschikbaar wanneer de budgetten dat toestaan en geeft meer nuance."
            ),
            "keyword_tags": json.dumps(["klimaatadaptatie", "hitte"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "html_lead")
        self.assertNotIn("Titel\n\nTitel", payload.excerpt_text)
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
                "Korte artikelparagraaf met enige context maar niet heel veel detail over een beleidsbrief en een eerste indruk van het onderwerp.\n\n"
                f"{PDF_EXTRACT_DELIMITER}\n\n"
                "Samenvatting\n\n"
                "Deze pdf paragraaf benoemt klimaatadaptatie en watergebruik in de industrie als gekoppelde opgave voor beleid. "
                "De samenvatting maakt duidelijk waarom dit document relevant is voor screening en verdere selectie. "
                "De tekst is expres lang genoeg om als zelfstandige excerpt-paragraaf te tellen voor de test.\n\n"
                "Nog een pdf paragraaf over KRW, droogte en industrieel watergebruik met voldoende context voor selectie en verdere afweging."
            ),
            "keyword_tags": json.dumps(["watergebruik", "klimaatadaptatie"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "html_lead_plus_pdf_summary_section")
        self.assertIn("ARTICLE_EXCERPT:", payload.excerpt_text)
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
                "Algemene inleiding met voldoende tekst maar zonder relevante trefwoorden voor de uiteindelijke selectie later in het document.\n\n"
                "Samenvatting\n\n"
                "Deze samenvattende paragraaf beschrijft de hoofdboodschap van het rapport en geeft voldoende context voor screening en selectie in een later stadium van de pipeline.\n\n"
                "Conclusies\n\n"
                "Deze paragraaf gaat over klimaatadaptatie, watergebruik en industrie en hoort daarom geselecteerd te worden op basis van de trefwoorden.\n\n"
                "Deze paragraaf gaat ook over klimaatadaptatie en droogte in relatie tot mobiliteit en bedrijventerreinen en versterkt het signaal."
            ),
            "keyword_tags": json.dumps(["watergebruik", "klimaatadaptatie"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "pdf_heading_plus_keyword")
        self.assertIn("hoofdboodschap van het rapport", payload.excerpt_text)
        self.assertIn("watergebruik", payload.excerpt_text)
        self.assertLessEqual(count_words(payload.excerpt_text), 1500)

    def test_payload_falls_back_to_in_memory_cleanup_and_handles_missing_tags(self):
        document = {
            "id": 4,
            "url": "https://example.com/d",
            "title": "Titel",
            "source_name": None,
            "publication_date": None,
            "discovery_method": None,
            "content_type": "html",
            "cleaned_text": "",
            "full_text": (
                "Titel\n\n"
                "Nieuwsbericht | 13-06-2024 | 10:10\n\n"
                "Deze paragraaf heeft voldoende lengte en context om als fallback excerpt gebruikt te worden door de builder."
            ),
            "keyword_tags": None,
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.keyword_tags, [])
        self.assertEqual(payload.source_name, None)
        self.assertIn("fallback excerpt", payload.excerpt_text)

    def test_payload_serialization_is_stable_json(self):
        document = {
            "id": 5,
            "url": "https://example.com/e",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "html",
            "cleaned_text": "Een lange paragraaf met genoeg woorden voor excerpt selectie in de screening payload builder en stabiele output.",
            "keyword_tags": json.dumps(["klimaatadaptatie"]),
        }

        payload = build_screening_input(document)
        serialized_once = serialize_screening_input(payload)
        serialized_twice = serialize_screening_input(payload)

        self.assertEqual(serialized_once, serialized_twice)
        self.assertIn('"excerpt_strategy"', serialized_once)

    def test_paragraph_keyword_score_counts_distinct_hits(self):
        paragraph = "Klimaatadaptatie en watergebruik zijn hier beide relevant. Klimaatadaptatie komt twee keer terug."
        score = paragraph_keyword_score(paragraph, ["klimaatadaptatie", "watergebruik", "klimaatadaptatie"])
        self.assertEqual(score, 2)

    def test_find_heading_like_paragraphs_recognizes_canonical_headings(self):
        paragraphs = [
            "Voorwoord",
            "Samenvatting",
            "Deze paragraaf is gewone tekst en geen heading.",
            "Conclusies:",
            "Aanbevelingen",
        ]
        indexes = find_heading_like_paragraphs(paragraphs)
        self.assertEqual(indexes, [1, 3, 4])

    def test_html_oversized_single_paragraph_is_split_and_capped(self):
        sentence = "Deze zin bevat voldoende woorden voor een realistische screening van een HTML artikel over klimaatadaptatie en waterveiligheid."
        big_paragraph = " ".join([sentence] * 70)
        document = {
            "id": 6,
            "url": "https://example.com/f",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "html",
            "cleaned_text": big_paragraph,
            "keyword_tags": json.dumps(["klimaatadaptatie"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "html_lead")
        self.assertLessEqual(count_words(payload.excerpt_text), 1500)
        self.assertLessEqual(len(payload.excerpt_text), 9000)

    def test_pdf_heading_tier_leaves_room_for_keyword_tier(self):
        summary_paragraph = " ".join(["Samenvattende context over brede beleidsimplicaties voor dit rapport."] * 35)
        keyword_paragraph = " ".join(["Klimaatadaptatie en watergebruik in de industrie zijn hier de centrale signalen."] * 18)
        document = {
            "id": 7,
            "url": "https://example.com/g",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "pdf",
            "cleaned_text": (
                "Samenvatting\n\n"
                f"{summary_paragraph}\n\n"
                "Aanbevelingen\n\n"
                f"{summary_paragraph}\n\n"
                f"{keyword_paragraph}"
            ),
            "keyword_tags": json.dumps(["klimaatadaptatie", "watergebruik"]),
        }

        payload = build_screening_input(document)

        self.assertIn("Samenvattende context", payload.excerpt_text)
        self.assertIn("Klimaatadaptatie en watergebruik", payload.excerpt_text)
        self.assertLessEqual(count_words(payload.excerpt_text), 1500)

    def test_long_pdf_gets_wider_budget(self):
        heading = "Samenvatting"
        summary_paragraph = " ".join(["Deze samenvatting beschrijft de hoofdpunten van het rapport en biedt brede context voor screening."] * 120)
        keyword_paragraph = " ".join(["Klimaatadaptatie en watergebruik in de industrie zijn een belangrijk thema in dit rapport."] * 180)
        filler_paragraph = " ".join(["Aanvullende context over beleid, uitvoering en ruimtelijke keuzes in Nederland."] * 220)
        cleaned_text = "\n\n".join([heading, summary_paragraph, keyword_paragraph, filler_paragraph, filler_paragraph, filler_paragraph])
        document = {
            "id": 8,
            "url": "https://example.com/h",
            "title": "Lang rapport",
            "source_name": "Bron",
            "publication_date": None,
            "discovery_method": "rss",
            "content_type": "pdf",
            "cleaned_text": cleaned_text,
            "keyword_tags": json.dumps(["klimaatadaptatie", "watergebruik"]),
        }

        payload = build_screening_input(document)

        self.assertEqual(payload.excerpt_strategy, "pdf_heading_plus_keyword")
        self.assertGreater(count_words(cleaned_text), 10000)
        self.assertGreater(count_words(payload.excerpt_text), 1500)
        self.assertLessEqual(count_words(payload.excerpt_text), 2000)


class ScreeningLLMRequestTests(unittest.TestCase):
    def test_build_llm_screening_request_keeps_only_reduced_fields(self):
        document = {
            "id": 9,
            "url": "https://example.com/i",
            "title": "Titel",
            "source_name": "Bron",
            "publication_date": datetime(2025, 5, 6, 9, 30, 0),
            "discovery_method": "listing",
            "content_type": "html",
            "cleaned_text": (
                "Deze paragraaf bevat voldoende inhoud om in de excerpt terecht te komen en "
                "vormt een bruikbare test voor het lean request object."
            ),
            "keyword_tags": json.dumps(["klimaatadaptatie", "watergebruik"]),
        }

        payload = build_screening_input(document)
        request = build_llm_screening_request(payload)
        request_json = json.loads(serialize_llm_screening_request(request))

        self.assertEqual(
            sorted(request_json.keys()),
            ["excerpt_text", "keyword_tags", "publication_date", "source_name", "title"],
        )
        self.assertNotIn("url", request_json)
        self.assertNotIn("discovery_method", request_json)
        self.assertNotIn("content_type", request_json)
        self.assertNotIn("has_linked_pdf", request_json)

    def test_compile_screening_system_prompt_uses_chunk_order(self):
        prompts = {
            "screening_system_context": "SYSTEM",
            "screening_task_instructions": "TASK",
            "screening_output_contract": "CONTRACT",
        }

        compiled = compile_screening_system_prompt(prompts)

        self.assertEqual(compiled, "SYSTEM\n\nTASK\n\nCONTRACT")

    def test_build_screening_user_message_wraps_json_payload(self):
        request_json = build_screening_user_message(
            build_llm_screening_request(
                build_screening_input(
                    {
                        "id": 10,
                        "url": "https://example.com/j",
                        "title": "Titel",
                        "source_name": "Bron",
                        "publication_date": None,
                        "discovery_method": "rss",
                        "content_type": "html",
                        "cleaned_text": (
                            "Deze paragraaf bevat voldoende inhoud om als excerpt naar de LLM "
                            "te sturen in JSON-vorm."
                        ),
                        "keyword_tags": json.dumps(["klimaatadaptatie"]),
                    }
                )
            )
        )

        self.assertTrue(request_json.startswith("SCREENING_INPUT_JSON:\n{"))
        self.assertIn('"title": "Titel"', request_json)
        self.assertNotIn('"url"', request_json)


class ScreeningOutputValidationTests(unittest.TestCase):
    def test_validate_screening_output_accepts_valid_controlled_schema(self):
        output = validate_screening_output(
            {
                "short_summary": "Bron over watergebruik in de industrie met duidelijke relevantie voor klimaatadaptatie.",
                "climate_adaptation_relevance_score": 8,
                "climate_adaptation_explanation": "De bron laat zien hoe droogte en waterbeschikbaarheid doorwerken in industriële keuzes.",
                "primary_opgave": "vergroening_industrie",
                "related_opgaves": ["klimaatadaptatie", "vergroening_industrie", "klimaatadaptatie"],
                "related_transities": ["energie_en_klimaattransitie", "energie_en_klimaattransitie"],
                "cross_domain_relevance_signal": "clear",
                "cross_domain_explanation": "klimaatadaptatie x vergroening_industrie: waterbeschikbaarheid en hitte dwingen tot andere investerings- en proceskeuzes.",
                "confidence": 0.82,
            }
        )

        self.assertEqual(output.primary_opgave, "vergroening_industrie")
        self.assertEqual(output.related_opgaves, ["klimaatadaptatie", "vergroening_industrie"])
        self.assertEqual(output.related_transities, ["energie_en_klimaattransitie"])

    def test_validate_screening_output_rejects_unknown_enum_labels(self):
        with self.assertRaises(ValueError):
            validate_screening_output(
                {
                    "short_summary": "Samenvatting.",
                    "climate_adaptation_relevance_score": 5,
                    "climate_adaptation_explanation": "Toelichting.",
                    "primary_opgave": "vrije_label_keuze",
                    "related_opgaves": ["klimaatadaptatie"],
                    "related_transities": ["energie_en_klimaattransitie"],
                    "cross_domain_relevance_signal": "none",
                    "cross_domain_explanation": "Geen duidelijke cross-domain koppeling.",
                    "confidence": 0.5,
                }
            )

    def test_validate_screening_output_allows_empty_cross_domain_explanation_for_none(self):
        output = validate_screening_output(
            {
                "short_summary": "Samenvatting.",
                "climate_adaptation_relevance_score": 5,
                "climate_adaptation_explanation": "Toelichting.",
                "primary_opgave": "klimaatadaptatie",
                "related_opgaves": [],
                "related_transities": [],
                "cross_domain_relevance_signal": "none",
                "cross_domain_explanation": "",
                "confidence": 0.7,
            }
        )

        self.assertEqual(output.cross_domain_explanation, "none")

    def test_validate_screening_output_requires_klimaatadaptatie_link_for_possible_or_clear(self):
        with self.assertRaises(ValueError):
            validate_screening_output(
                {
                    "short_summary": "Samenvatting.",
                    "climate_adaptation_relevance_score": 6,
                    "climate_adaptation_explanation": "Toelichting.",
                    "primary_opgave": "klimaatadaptatie",
                    "related_opgaves": ["klimaatadaptatie", "verduurzamen_gebouwde_omgeving"],
                    "related_transities": ["energie_en_klimaattransitie"],
                    "cross_domain_relevance_signal": "possible",
                    "cross_domain_explanation": "Er is een koppeling met de gebouwde omgeving, maar die wordt niet expliciet genoeg gemaakt.",
                    "confidence": 0.6,
                }
            )

    def test_screening_output_schema_reflects_adjusted_plan(self):
        schema = screening_output_schema()

        self.assertIn("primary_opgave", schema)
        self.assertIn("related_opgaves", schema)
        self.assertIn("related_transities", schema)
        self.assertIn("cross_domain_explanation", schema)
        self.assertNotIn("rvo_actionability_signal", schema)
        self.assertNotIn("rvo_actionability_explanation", schema)


if __name__ == "__main__":
    unittest.main()

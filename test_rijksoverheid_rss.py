import unittest
from unittest.mock import patch, Mock

from modules.filter import check_relevance
from modules.ingest import MultiSourceIngester
from modules.source_metadata import (
    classify_doc_type,
    get_parliament_source_names,
    get_rijksoverheid_source_names,
    is_rijksoverheid_rss_source,
)


class RijksoverheidSourceMetadataTests(unittest.TestCase):
    def test_detects_rijksoverheid_rss_family(self):
        source = {
            "method": "rss",
            "source_name": "Rijksoverheid - Kamerstukken",
            "url": "https://feeds.rijksoverheid.nl/kamerstukken.rss",
            "options": {},
        }
        self.assertTrue(is_rijksoverheid_rss_source(source))

    def test_classifies_parliamentary_titles(self):
        options = {"classification_profile": "rijksoverheid_rss"}
        self.assertEqual(
            classify_doc_type(
                title="Beantwoording Kamervragen over klimaatadaptatie in de gebouwde omgeving",
                url="https://www.rijksoverheid.nl/documenten/kamerstukken/2026/03/27/test",
                source_name="Rijksoverheid - Kamerstukken",
                source_options=options,
            ),
            "beantwoording_kamervragen",
        )
        self.assertEqual(
            classify_doc_type(
                title="Kamerbrief over aanpak water en bodem",
                url="https://www.rijksoverheid.nl/documenten/kamerstukken/2026/03/27/test",
                source_name="Rijksoverheid - Kamerstukken",
                source_options=options,
            ),
            "kamerbrief",
        )

    def test_classifies_news_and_publication_fallbacks(self):
        options = {"classification_profile": "rijksoverheid_rss"}
        self.assertEqual(
            classify_doc_type(
                title="Maatregelen voor weerbare wijken",
                url="https://www.rijksoverheid.nl/actueel/nieuws/2026/03/27/maatregelen-voor-weerbare-wijken",
                source_name="Min. VRO - Nieuws",
                source_options=options,
            ),
            "nieuwsbericht",
        )
        self.assertEqual(
            classify_doc_type(
                title="Algemene publicatie over uitvoeringsbeleid",
                url="https://www.rijksoverheid.nl/documenten/publicaties/2026/03/27/publicatie",
                source_name="Rijksoverheid - Klimaat Documenten",
                source_options=options,
            ),
            "publicatie",
        )

    def test_returns_rijksoverheid_and_parliament_source_names(self):
        sources = [
            {
                "method": "rss",
                "source_name": "Rijksoverheid - Kamerstukken",
                "url": "https://feeds.rijksoverheid.nl/kamerstukken.rss",
                "options": {},
            },
            {
                "method": "rss",
                "source_name": "Rijksoverheid - Klimaat Nieuws",
                "url": "https://feeds.rijksoverheid.nl/onderwerpen/klimaatverandering/nieuws.rss",
                "options": {},
            },
            {
                "method": "rss",
                "source_name": "Tweede Kamer",
                "url": "https://www.tweedekamer.nl/rss.xml",
                "options": {},
            },
        ]
        self.assertEqual(
            get_parliament_source_names(sources),
            ["Rijksoverheid - Kamerstukken"],
        )
        self.assertEqual(
            get_rijksoverheid_source_names(sources),
            ["Rijksoverheid - Kamerstukken", "Rijksoverheid - Klimaat Nieuws"],
        )


class RijksoverheidRecheckTests(unittest.TestCase):
    def test_pdf_recheck_option_enabled(self):
        ingester = MultiSourceIngester()
        source = {
            "method": "rss",
            "source_name": "Rijksoverheid - Klimaat Documenten",
            "url": "https://feeds.rijksoverheid.nl/onderwerpen/klimaatverandering/documenten.rss",
            "options": {"recheck_linked_pdf": True},
        }
        self.assertTrue(ingester._should_recheck_linked_pdf(source))

    @patch("modules.ingest.requests.get")
    def test_pdf_recheck_can_recover_relevance(self, mock_get):
        ingester = MultiSourceIngester()
        source = {
            "method": "rss",
            "source_name": "Rijksoverheid - Klimaat Documenten",
            "url": "https://feeds.rijksoverheid.nl/onderwerpen/klimaatverandering/documenten.rss",
            "options": {"recheck_linked_pdf": True},
        }
        initial_result = check_relevance("Algemene titel", "Korte beschrijving zonder signaal")

        response = Mock()
        response.text = (
            "<html><head><title>Algemene titel</title></head>"
            "<body><main>Procesmatige toelichting zonder duidelijke trefwoorden.</main></body></html>"
        )
        response.headers = {"Content-Type": "text/html"}
        response.raise_for_status = Mock()
        mock_get.return_value = response

        with patch.object(
            ingester.fetcher,
            "extract_linked_pdf_excerpt",
            return_value=("Deze pdf gaat over klimaatadaptatie en wateroverlast in stedelijk gebied.", "https://example.com/a.pdf"),
        ):
            _, description, result = ingester._recheck_candidate_relevance(
                title="Algemene titel",
                description="Korte beschrijving zonder signaal",
                link="https://www.rijksoverheid.nl/documenten/test",
                filter_result=initial_result,
                source=source,
            )

        self.assertTrue(result.is_relevant)
        self.assertIn("klimaatadaptatie", description)


if __name__ == "__main__":
    unittest.main()

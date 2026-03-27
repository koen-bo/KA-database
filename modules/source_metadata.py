"""
Source-specific metadata helpers.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import config


RIJKSOVERHEID_DOC_TYPES = [
    "motie",
    "amendement",
    "kamervraag",
    "beantwoording_kamervragen",
    "kamerbrief",
    "kabinetsreactie",
    "beleidsnota",
    "beslisnota",
    "wetsvoorstel",
    "nota_naar_aanleiding_van_verslag",
    "verslag",
    "regeling_of_besluit",
    "rapport_of_bijlage",
    "publicatie",
    "nieuwsbericht",
    "onbekend",
]

PARLIAMENT_DOC_TYPES = {
    "motie",
    "amendement",
    "kamervraag",
    "beantwoording_kamervragen",
    "kamerbrief",
    "kabinetsreactie",
    "beleidsnota",
    "beslisnota",
    "wetsvoorstel",
    "nota_naar_aanleiding_van_verslag",
    "verslag",
    "regeling_of_besluit",
}


def is_rijksoverheid_rss_source(source: config.SourceConfig) -> bool:
    """Return True when the source belongs to the feeds.rijksoverheid.nl RSS family."""
    try:
        parsed = urlparse(source.get("url", ""))
    except Exception:
        return False
    return source.get("method") == "rss" and parsed.netloc == "feeds.rijksoverheid.nl"


def classify_doc_type(
    title: str,
    url: str,
    source_name: str,
    source_options: dict | None = None,
) -> str | None:
    """Classify a document type for sources that opt into a known profile."""
    options = source_options or {}
    profile = (options.get("classification_profile") or "").strip().lower()
    if not profile:
        return None
    if profile == "rijksoverheid_rss":
        return _classify_rijksoverheid_doc_type(title=title, url=url, source_name=source_name)
    return None


def _classify_rijksoverheid_doc_type(title: str, url: str, source_name: str) -> str:
    text = _normalize_text(f"{title} {source_name} {url}")
    source_text = _normalize_text(source_name)
    path = (urlparse(url).path if url else "").lower()

    rules: list[tuple[str, tuple[str, ...]]] = [
        ("beantwoording_kamervragen", ("beantwoording kamervragen", "beantwoordt kamervragen")),
        ("kamervraag", ("kamervragen", "kamervraag")),
        ("nota_naar_aanleiding_van_verslag", ("nota naar aanleiding van het verslag", "nota nav verslag")),
        ("wetsvoorstel", ("wetsvoorstel", "wetgevingsoverleg", "initiatiefwet")),
        ("kabinetsreactie", ("kabinetsreactie",)),
        ("kamerbrief", ("kamerbrief", "verzamelbrief", "voorjaarsbrief", "najaarsbrief")),
        ("motie", ("motie",)),
        ("amendement", ("amendement",)),
        ("beleidsnota", ("beleidsnota", "beleidsvisie", "beleidsprogramma")),
        ("beslisnota", ("beslisnota",)),
        ("verslag", ("verslag", "eindverslag", "jaarverslag")),
        ("regeling_of_besluit", ("regeling", "ontwerpbesluit", "besluit", "algemene maatregel van bestuur")),
        ("rapport_of_bijlage", ("rapport", "bijlage", "monitoringsbrief", "onderzoek", "evaluatie")),
    ]

    for doc_type, markers in rules:
        if any(marker in text for marker in markers):
            return doc_type

    if "/documenten/publicaties/" in path or " publicaties" in source_text or source_text.endswith(" publicaties"):
        return "publicatie"
    if "/documenten/rapporten/" in path or "/documenten/bijlagen/" in path:
        return "rapport_of_bijlage"
    if "/actueel/nieuws/" in path or " nieuws" in source_text:
        return "nieuwsbericht"
    if "/documenten/" in path:
        return "publicatie"
    return "onbekend"


def get_parliament_source_names(sources: list[config.SourceConfig]) -> list[str]:
    """Return source names that should appear in the parliament quick filter."""
    names: list[str] = []
    for source in sources:
        if not is_rijksoverheid_rss_source(source):
            continue
        url = (source.get("url") or "").lower()
        source_name = source.get("source_name", "")
        if "kamerstukken" in url or "kamerstukken" in source_name.lower():
            names.append(source_name)
    return sorted(set(names))


def get_rijksoverheid_source_names(sources: list[config.SourceConfig]) -> list[str]:
    """Return all configured Rijksoverheid RSS source names."""
    return sorted({source["source_name"] for source in sources if is_rijksoverheid_rss_source(source)})


def _normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"[-_/]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()

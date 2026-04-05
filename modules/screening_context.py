"""
Curated screening context assets and deterministic selection helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
from typing import Any

import config


CORE_CONTEXT_VERSION = "v1"
FACTUAL_LENS_LIMIT = 3
FACTUAL_FOOTHOLD_LIMIT = 4
EXPLORATORY_LENS_LIMIT = 2
EXPLORATORY_FOOTHOLD_LIMIT = 3

TITLE_ZONE = "title"
KEYWORD_ZONE = "keyword_tags"
EXCERPT_ZONE = "excerpt_text"

TITLE_WEIGHT = 4
KEYWORD_WEIGHT = 2
EXCERPT_WEIGHT = 1
BOOST_MULTIPLIER = 2
EXCLUDE_PENALTY = 4
MIN_SELECTION_SCORE = 1


@dataclass(frozen=True)
class RankedContextItem:
    id: str
    title: str
    score: int
    matched_terms: list[str]
    matched_zones: dict[str, int]


@dataclass(frozen=True)
class ScreeningContextSelection:
    core_context_version: str
    selected_lenses: list[RankedContextItem]
    selected_footholds: list[RankedContextItem]
    exploratory_lenses: list[RankedContextItem]
    exploratory_footholds: list[RankedContextItem]
    selection_metadata: dict[str, Any]


def load_core_context(filepath: str | None = None) -> str:
    path = filepath or config.SCREENING_CORE_CONTEXT_FILE
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        raise ValueError("core context file is empty")
    return text


def load_strategic_lenses(filepath: str | None = None) -> list[dict[str, Any]]:
    return _load_catalog(
        filepath or config.SCREENING_LENSES_FILE,
        required_fields=(
            "id",
            "title",
            "core_question",
            "signals_to_notice",
            "why_it_matters",
            "runtime_guidance",
            "selection_terms",
        ),
        label="strategic lenses",
    )


def load_rvo_footholds(filepath: str | None = None) -> list[dict[str, Any]]:
    return _load_catalog(
        filepath or config.SCREENING_FOOTHOLDS_FILE,
        required_fields=(
            "id",
            "title",
            "description",
            "leverage",
            "typical_triggers",
            "runtime_guidance",
            "selection_terms",
        ),
        label="RVO footholds",
    )


def load_regression_fixtures(filepath: str | None = None) -> list[dict[str, Any]]:
    return _load_catalog(
        filepath or config.SCREENING_REGRESSION_FIXTURES_FILE,
        required_fields=("id", "title", "keyword_tags", "excerpt_text"),
        label="screening regression fixtures",
    )


def select_context_for_document(
    title: str,
    keyword_tags: list[str],
    excerpt_text: str,
    lenses: list[dict[str, Any]] | None = None,
    footholds: list[dict[str, Any]] | None = None,
) -> ScreeningContextSelection:
    lens_catalog = load_strategic_lenses() if lenses is None else lenses
    foothold_catalog = load_rvo_footholds() if footholds is None else footholds
    zone_texts = {
        TITLE_ZONE: _normalize_text(title or ""),
        KEYWORD_ZONE: _normalize_text(" ".join(keyword_tags or [])),
        EXCERPT_ZONE: _normalize_text(excerpt_text or ""),
    }

    ranked_lenses = _rank_catalog(lens_catalog, zone_texts)
    ranked_footholds = _rank_catalog(foothold_catalog, zone_texts)

    selected_lenses = ranked_lenses[:FACTUAL_LENS_LIMIT]
    selected_footholds = ranked_footholds[:FACTUAL_FOOTHOLD_LIMIT]
    exploratory_lenses = ranked_lenses[:EXPLORATORY_LENS_LIMIT]
    exploratory_footholds = ranked_footholds[:EXPLORATORY_FOOTHOLD_LIMIT]

    return ScreeningContextSelection(
        core_context_version=CORE_CONTEXT_VERSION,
        selected_lenses=selected_lenses,
        selected_footholds=selected_footholds,
        exploratory_lenses=exploratory_lenses,
        exploratory_footholds=exploratory_footholds,
        selection_metadata={
            "minimum_score": MIN_SELECTION_SCORE,
            "weights": {
                TITLE_ZONE: TITLE_WEIGHT,
                KEYWORD_ZONE: KEYWORD_WEIGHT,
                EXCERPT_ZONE: EXCERPT_WEIGHT,
            },
            "limits": {
                "factual_lenses": FACTUAL_LENS_LIMIT,
                "factual_footholds": FACTUAL_FOOTHOLD_LIMIT,
                "exploratory_lenses": EXPLORATORY_LENS_LIMIT,
                "exploratory_footholds": EXPLORATORY_FOOTHOLD_LIMIT,
            },
            "factual_lenses_truncated_by_fit": len(ranked_lenses) < FACTUAL_LENS_LIMIT,
            "factual_footholds_truncated_by_fit": len(ranked_footholds) < FACTUAL_FOOTHOLD_LIMIT,
            "exploratory_lenses_truncated_by_fit": len(ranked_lenses) < EXPLORATORY_LENS_LIMIT,
            "exploratory_footholds_truncated_by_fit": len(ranked_footholds) < EXPLORATORY_FOOTHOLD_LIMIT,
        },
    )


def serialize_context_selection(selection: ScreeningContextSelection) -> str:
    return json.dumps(asdict(selection), ensure_ascii=False, sort_keys=True)


def annotate_context_selection_with_factual_footholds(
    context_json: str,
    returned_foothold_ids: list[str],
) -> str:
    data = json.loads(context_json)
    if not isinstance(data, dict):
        return context_json

    selected_footholds = data.get("selected_footholds", [])
    selected_ids = {
        str(item.get("id")).strip()
        for item in selected_footholds
        if isinstance(item, dict) and str(item.get("id")).strip()
    }
    returned_ids = [item for item in returned_foothold_ids if item]
    matched = [item for item in returned_ids if item in selected_ids]
    misses = [item for item in returned_ids if item not in selected_ids]
    data["factual_output_foothold_ids"] = returned_ids
    data["factual_selector_match_ids"] = matched
    data["factual_selector_miss_ids"] = misses
    data["has_selector_miss"] = bool(misses)
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def merge_context_metadata(context_json: str, **metadata: Any) -> str:
    data = json.loads(context_json)
    if not isinstance(data, dict):
        return context_json
    for key, value in metadata.items():
        data[key] = value
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def format_context_block(
    core_context: str,
    selected_lenses: list[RankedContextItem],
    selected_footholds: list[RankedContextItem],
    lens_catalog: list[dict[str, Any]] | None = None,
    foothold_catalog: list[dict[str, Any]] | None = None,
) -> str:
    lenses_by_id = {item["id"]: item for item in (lens_catalog or load_strategic_lenses())}
    footholds_by_id = {item["id"]: item for item in (foothold_catalog or load_rvo_footholds())}

    parts = [f"CORE CONTEXT:\n{core_context.strip()}"]

    if selected_lenses:
        lens_lines: list[str] = []
        for selected in selected_lenses:
            record = lenses_by_id.get(selected.id, {})
            lens_lines.append(
                "\n".join(
                    [
                        f"- {selected.title} [{selected.id}]",
                        f"  Kernvraag: {record.get('core_question', '')}",
                        f"  Waarom dit ertoe doet: {record.get('why_it_matters', '')}",
                        f"  Runtime: {record.get('runtime_guidance', '')}",
                        f"  Score: {selected.score}",
                        f"  Match: {', '.join(selected.matched_terms) if selected.matched_terms else 'geen expliciete termmatch'}",
                        f"  Zones: {_format_matched_zones(selected.matched_zones)}",
                    ]
                )
            )
        parts.append("SELECTED STRATEGIC LENSES:\n" + "\n".join(lens_lines))

    if selected_footholds:
        foothold_lines: list[str] = []
        for selected in selected_footholds:
            record = footholds_by_id.get(selected.id, {})
            triggers = record.get("typical_triggers", [])
            foothold_lines.append(
                "\n".join(
                    [
                        f"- {selected.title} [{selected.id}]",
                        f"  Beschrijving: {record.get('description', '')}",
                        f"  Hefboom: {record.get('leverage', '')}",
                        f"  Triggers: {', '.join(triggers[:4])}",
                        f"  Runtime: {record.get('runtime_guidance', '')}",
                        f"  Score: {selected.score}",
                        f"  Match: {', '.join(selected.matched_terms) if selected.matched_terms else 'geen expliciete termmatch'}",
                        f"  Zones: {_format_matched_zones(selected.matched_zones)}",
                    ]
                )
            )
        parts.append("SELECTED RVO FOOTHOLDS:\n" + "\n".join(foothold_lines))

    return "\n\n".join([part for part in parts if part.strip()]).strip()


def context_titles(items: list[RankedContextItem]) -> list[str]:
    return [item.title for item in items]


def _load_catalog(
    filepath: str,
    required_fields: tuple[str, ...],
    label: str,
) -> list[dict[str, Any]]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or not data:
        raise ValueError(f"{label} file must contain a non-empty list")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{label} item {index} must be an object")
        missing = [field for field in required_fields if field not in item]
        if missing:
            raise ValueError(f"{label} item {index} missing required fields: {', '.join(missing)}")
        item_id = str(item["id"]).strip()
        if not item_id:
            raise ValueError(f"{label} item {index} has empty id")
        if item_id in seen_ids:
            raise ValueError(f"{label} contains duplicate id: {item_id}")
        seen_ids.add(item_id)
        validated_item = dict(item)
        validated_item["id"] = item_id
        validated_item["title"] = str(item["title"]).strip()
        validated_item["selection_terms"] = _normalize_terms(item.get("selection_terms", []), "selection_terms")
        validated_item["boost_terms"] = _normalize_terms(item.get("boost_terms", []), "boost_terms", required=False)
        validated_item["exclude_terms"] = _normalize_terms(item.get("exclude_terms", []), "exclude_terms", required=False)
        validated.append(validated_item)

    return validated


def _normalize_terms(value: Any, field_name: str, required: bool = True) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    normalized: list[str] = []
    for item in value:
        text = _normalize_text(str(item))
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _rank_catalog(catalog: list[dict[str, Any]], zone_texts: dict[str, str]) -> list[RankedContextItem]:
    ranked: list[RankedContextItem] = []
    for item in catalog:
        matched_terms: list[str] = []
        matched_zones: dict[str, int] = {}
        score = 0

        for term in item.get("selection_terms", []):
            term_score, zones = _score_term(term, zone_texts, multiplier=1)
            if term_score:
                score += term_score
                matched_terms.append(term)
                for zone_name, occurrences in zones.items():
                    matched_zones[zone_name] = matched_zones.get(zone_name, 0) + occurrences

        for term in item.get("boost_terms", []):
            term_score, zones = _score_term(term, zone_texts, multiplier=BOOST_MULTIPLIER)
            if term_score:
                score += term_score
                if term not in matched_terms:
                    matched_terms.append(term)
                for zone_name, occurrences in zones.items():
                    matched_zones[zone_name] = matched_zones.get(zone_name, 0) + occurrences

        for term in item.get("exclude_terms", []):
            term_occurrences = _count_term_occurrences(term, zone_texts)
            if term_occurrences:
                score -= EXCLUDE_PENALTY * sum(term_occurrences.values())

        if score > 0:
            title_terms = _normalize_terms(item.get("title", "").split(), "title_terms")
            for term in title_terms[:3]:
                if len(term) < 6 or term in matched_terms:
                    continue
                occurrences = _term_occurrences(term, zone_texts[TITLE_ZONE])
                if occurrences:
                    score += 1
                    matched_terms.append(term)
                    matched_zones[TITLE_ZONE] = matched_zones.get(TITLE_ZONE, 0) + occurrences

        if score >= MIN_SELECTION_SCORE:
            ranked.append(
                RankedContextItem(
                    id=item["id"],
                    title=item["title"],
                    score=score,
                    matched_terms=sorted(matched_terms)[:8],
                    matched_zones=dict(sorted(matched_zones.items())),
                )
            )

    return sorted(
        ranked,
        key=lambda item: (-item.score, item.title.lower(), item.id),
    )


def _score_term(
    term: str,
    zone_texts: dict[str, str],
    multiplier: int,
) -> tuple[int, dict[str, int]]:
    occurrences = _count_term_occurrences(term, zone_texts)
    score = (
        occurrences.get(TITLE_ZONE, 0) * TITLE_WEIGHT
        + occurrences.get(KEYWORD_ZONE, 0) * KEYWORD_WEIGHT
        + occurrences.get(EXCERPT_ZONE, 0) * EXCERPT_WEIGHT
    ) * multiplier
    return score, occurrences


def _count_term_occurrences(term: str, zone_texts: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for zone_name, zone_text in zone_texts.items():
        occurrences = _term_occurrences(term, zone_text)
        if occurrences:
            counts[zone_name] = occurrences
    return counts


def _term_occurrences(term: str, normalized_text: str) -> int:
    if not term or not normalized_text:
        return 0
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return len(re.findall(pattern, normalized_text))


def _format_matched_zones(matched_zones: dict[str, int]) -> str:
    if not matched_zones:
        return "geen zonehit"
    return ", ".join(f"{zone}={count}" for zone, count in matched_zones.items())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

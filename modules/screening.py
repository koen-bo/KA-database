"""
Screening text cleanup and payload helpers.

Step 1: deterministic, no-LLM preprocessing for stored document text.
Step 2: deterministic screening payload construction for later LLM use.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from functools import lru_cache
import json
import re
from typing import Any, Literal, Optional, TypedDict

from modules.screening_context import (
    RankedContextItem,
    format_context_block,
    load_core_context,
    load_rvo_footholds,
)


PDF_EXTRACT_DELIMITER = "[PDF EXTRACT]"
CLEANUP_VERSION = "v1"

HTML_TARGET_WORDS = 1200
HTML_MAX_WORDS = 1500
HTML_MAX_CHARS = 9000

HTML_WITH_PDF_ARTICLE_TARGET_WORDS = 900
HTML_WITH_PDF_ARTICLE_MAX_WORDS = 900
HTML_WITH_PDF_SHORT_THRESHOLD_WORDS = 900
HTML_WITH_PDF_TOTAL_MAX_WORDS = 1500
HTML_WITH_PDF_TOTAL_MAX_CHARS = 9000
HTML_WITH_PDF_LONG_TOTAL_MAX_WORDS = 1800
HTML_WITH_PDF_LONG_TOTAL_MAX_CHARS = 12000

PDF_TOTAL_TARGET_WORDS = 1400
PDF_TOTAL_MAX_WORDS = 1500
PDF_TOTAL_MAX_CHARS = 10000
PDF_TIER1_TARGET_WORDS = 500
PDF_TIER1_MAX_WORDS = 600
PDF_POST_HEADING_WINDOW = 2
LONG_PDF_THRESHOLD_WORDS = 10000
LONG_PDF_TOTAL_TARGET_WORDS = 1800
LONG_PDF_TOTAL_MAX_WORDS = 2000
LONG_PDF_TOTAL_MAX_CHARS = 12000
LONG_PDF_TIER1_TARGET_WORDS = 600
LONG_PDF_TIER1_MAX_WORDS = 700

MIN_SUBSTANTIVE_CHARS = 80
MIN_SUBSTANTIVE_WORDS = 12
SENTENCE_GROUP_MIN_WORDS = 120
SENTENCE_GROUP_MAX_WORDS = 220

CANONICAL_PDF_HEADINGS = (
    "samenvatting",
    "managementsamenvatting",
    "management summary",
    "abstract",
    "conclusie",
    "conclusies",
    "aanbevelingen",
    "aanbeveling",
    "kernbevindingen",
    "bevindingen",
    "slotbeschouwing",
)

@dataclass(frozen=True)
class CleanupResult:
    cleaned_text: str
    has_pdf_section: bool
    cleanup_version: str = CLEANUP_VERSION


@dataclass(frozen=True)
class ScreeningInput:
    document_id: int
    url: str
    title: str
    source_name: Optional[str]
    publication_date: Optional[str]
    discovery_method: Optional[str]
    content_type: Optional[str]
    has_linked_pdf: bool
    keyword_tags: list[str]
    excerpt_strategy: str
    excerpt_text: str


@dataclass(frozen=True)
class LLMScreeningRequest:
    title: str
    source_name: Optional[str]
    publication_date: Optional[str]
    keyword_tags: list[str]
    excerpt_text: str


@dataclass(frozen=True)
class ExploratoryLLMScreeningRequest:
    title: str
    source_name: Optional[str]
    publication_date: Optional[str]
    keyword_tags: list[str]
    excerpt_text: str
    factual_analysis: dict[str, Any]


@dataclass(frozen=True)
class FactualFoothold:
    id: str
    rationale: str


@dataclass(frozen=True)
class FactualActorGroup:
    label: str
    role: str


@dataclass(frozen=True)
class FactualRelevanceReason:
    title: str
    explanation: str


@dataclass(frozen=True)
class FactualScreeningOutput:
    factual_summary: str
    what_is_changing: str
    actors_and_sectors: str
    actor_groups: list[FactualActorGroup]
    opgave_relevance: str
    relevance_reasons: list[FactualRelevanceReason]
    footholds: list[FactualFoothold]
    evidence_quotes: list[str]
    uncertainties: list[str]
    opgave_signal_score: int
    rvo_link_path: Literal["direct_operational", "mixed", "strategic_indirect", "weak"]
    score_defense: str
    confidence: float


@dataclass(frozen=True)
class ExploratoryHypothesis:
    hypothesis: str
    mechanism: str
    foothold_ids: list[str]
    evidence_refs: list[str]
    certainty: Literal["likely", "possible", "speculative"]
    verification: str


@dataclass(frozen=True)
class ExploratoryScreeningOutput:
    exploration_decision: Literal["analyze", "not_needed"]
    decision_rationale: str
    strategic_memo: str
    hypotheses: list[ExploratoryHypothesis]


@dataclass(frozen=True)
class NormalizedFactualResult:
    output: FactualScreeningOutput
    warnings: list[str]
    repairs_applied: list[str]


@dataclass(frozen=True)
class NormalizedExploratoryResult:
    output: ExploratoryScreeningOutput
    warnings: list[str]
    repairs_applied: list[str]


class DocumentLike(TypedDict, total=False):
    id: int
    url: str
    title: str
    source_name: Optional[str]
    publication_date: Optional[str]
    discovery_method: Optional[str]
    content_type: Optional[str]
    local_file_path: Optional[str]
    full_text: Optional[str]
    cleaned_text: Optional[str]
    keyword_tags: Optional[str]


class FactualScreeningOutputDict(TypedDict):
    factual_summary: str
    what_is_changing: str
    actors_and_sectors: str
    actor_groups: list[dict[str, str]]
    opgave_relevance: str
    relevance_reasons: list[dict[str, str]]
    footholds: list[dict[str, str]]
    evidence_quotes: list[str]
    uncertainties: list[str]
    opgave_signal_score: int
    rvo_link_path: str
    score_defense: str
    confidence: float


class ExploratoryScreeningOutputDict(TypedDict):
    exploration_decision: str
    decision_rationale: str
    strategic_memo: str
    hypotheses: list[dict[str, Any]]


def clean_document_text(
    full_text: Optional[str],
    content_type: Optional[str],
    local_file_path: Optional[str] = None,
) -> CleanupResult:
    """
    Clean stored text for later screening/excerpt selection.

    Uses content_type as the primary signal, but preserves merged HTML+PDF
    documents when the stable PDF delimiter is present in full_text.
    """
    raw_text = (full_text or "").strip()
    if not raw_text:
        return CleanupResult(cleaned_text="", has_pdf_section=False)

    if PDF_EXTRACT_DELIMITER in raw_text:
        article_text, pdf_text = split_cleaned_sections(raw_text)
        cleaned_article = _clean_html_text(article_text or "")
        cleaned_pdf = _clean_pdf_text(pdf_text or "")
        parts = [part for part in (cleaned_article, cleaned_pdf) if part]
        if len(parts) == 2:
            merged = f"{cleaned_article}\n\n{PDF_EXTRACT_DELIMITER}\n\n{cleaned_pdf}".strip()
        else:
            merged = parts[0] if parts else ""
        return CleanupResult(cleaned_text=merged, has_pdf_section=bool(cleaned_pdf))

    is_pdf = (content_type or "").lower() == "pdf"
    cleaned_text = _clean_pdf_text(raw_text) if is_pdf else _clean_html_text(raw_text)
    return CleanupResult(cleaned_text=cleaned_text, has_pdf_section=False)


def split_cleaned_sections(cleaned_text: Optional[str]) -> tuple[str, Optional[str]]:
    """Split cleaned text into article and PDF sections when the stable delimiter exists."""
    text = (cleaned_text or "").strip()
    if PDF_EXTRACT_DELIMITER not in text:
        return text, None
    article_text, pdf_text = text.split(PDF_EXTRACT_DELIMITER, 1)
    return article_text.strip(), pdf_text.strip() or None


def extract_cleaned_paragraphs(cleaned_text: Optional[str]) -> list[str]:
    """Return non-empty paragraphs from cleaned text."""
    if not cleaned_text:
        return []
    return [part.strip() for part in cleaned_text.split("\n\n") if part.strip()]


def filter_substantive_paragraphs(
    paragraphs: list[str],
    title: Optional[str] = None,
) -> list[str]:
    """Drop obvious metadata leftovers and keep only substantive paragraphs."""
    title_norm = _normalize_compare_text(title or "")
    filtered: list[str] = []
    for paragraph in paragraphs:
        candidate = re.sub(r"\s+", " ", paragraph).strip()
        if not candidate:
            continue
        if title_norm and _normalize_compare_text(candidate) == title_norm:
            continue
        if _looks_like_source_date_prefix(candidate):
            continue
        if _is_page_number_line(candidate):
            continue
        if len(candidate) < MIN_SUBSTANTIVE_CHARS and len(candidate.split()) < MIN_SUBSTANTIVE_WORDS:
            continue
        filtered.append(candidate)
    return filtered


def paragraph_keyword_score(paragraph: str, keyword_tags: list[str]) -> int:
    """Count distinct stored keyword tags that appear in a paragraph."""
    lowered = paragraph.lower()
    return sum(1 for tag in set(keyword_tags) if tag and tag in lowered)


def build_screening_input(document: Any) -> ScreeningInput:
    """
    Build the deterministic screening payload for a document.

    Uses cleaned_text when available and falls back to in-memory cleanup.
    """
    cleaned_text = (_get_document_value(document, "cleaned_text") or "").strip()
    if not cleaned_text:
        cleanup_result = clean_document_text(
            full_text=_get_document_value(document, "full_text"),
            content_type=_get_document_value(document, "content_type"),
            local_file_path=_get_document_value(document, "local_file_path"),
        )
        cleaned_text = cleanup_result.cleaned_text

    article_text, pdf_text = split_cleaned_sections(cleaned_text)
    keyword_tags = _parse_keyword_tags(_get_document_value(document, "keyword_tags"))
    content_type = _string_or_none(_get_document_value(document, "content_type"))
    has_linked_pdf = content_type == "html" and bool(pdf_text)
    title = _string_or_empty(_get_document_value(document, "title"))

    if (content_type or "").lower() == "pdf":
        excerpt_strategy, excerpt_text = _build_pdf_excerpt(pdf_text or article_text, keyword_tags, title)
    elif has_linked_pdf:
        excerpt_strategy, excerpt_text = _build_html_with_pdf_excerpt(article_text, pdf_text or "", keyword_tags, title)
    else:
        excerpt_strategy, excerpt_text = _build_html_excerpt(article_text, title)

    return ScreeningInput(
        document_id=int(_get_document_value(document, "id") or 0),
        url=_string_or_empty(_get_document_value(document, "url")),
        title=title,
        source_name=_string_or_none(_get_document_value(document, "source_name")),
        publication_date=_format_publication_date(_get_document_value(document, "publication_date")),
        discovery_method=_string_or_none(_get_document_value(document, "discovery_method")),
        content_type=content_type,
        has_linked_pdf=has_linked_pdf,
        keyword_tags=keyword_tags,
        excerpt_strategy=excerpt_strategy,
        excerpt_text=excerpt_text,
    )


def serialize_screening_input(payload: ScreeningInput) -> str:
    """Serialize screening input to stable JSON for later persistence."""
    return json.dumps(asdict(payload), ensure_ascii=False, sort_keys=True)


def build_llm_screening_request(payload: ScreeningInput) -> LLMScreeningRequest:
    """Reduce internal screening input to the lean factual request object sent to the LLM."""
    return LLMScreeningRequest(
        title=payload.title,
        source_name=payload.source_name,
        publication_date=payload.publication_date,
        keyword_tags=payload.keyword_tags,
        excerpt_text=payload.excerpt_text,
    )


def serialize_llm_screening_request(request: LLMScreeningRequest) -> str:
    """Serialize the actual factual request payload that will be sent to the LLM."""
    return json.dumps(asdict(request), ensure_ascii=False, sort_keys=True)


def build_exploratory_llm_screening_request(
    payload: ScreeningInput,
    factual_output: FactualScreeningOutput,
) -> ExploratoryLLMScreeningRequest:
    """Build the exploratory request from the document excerpt plus the factual result."""
    return ExploratoryLLMScreeningRequest(
        title=payload.title,
        source_name=payload.source_name,
        publication_date=payload.publication_date,
        keyword_tags=payload.keyword_tags,
        excerpt_text=payload.excerpt_text,
        factual_analysis=asdict(factual_output),
    )


def serialize_exploratory_llm_screening_request(request: ExploratoryLLMScreeningRequest) -> str:
    """Serialize the exploratory request payload that will be sent to the LLM."""
    return json.dumps(asdict(request), ensure_ascii=False, sort_keys=True)


def compile_factual_system_prompt(
    prompts: dict[str, str],
    selected_lenses: list[RankedContextItem],
    selected_footholds: list[RankedContextItem],
    core_context_text: str | None = None,
) -> str:
    return _compile_lane_system_prompt(
        prompts=prompts,
        intro_key="factual_system_intro",
        task_key="factual_task_instructions",
        output_key="factual_output_contract",
        selected_lenses=selected_lenses,
        selected_footholds=selected_footholds,
        core_context_text=core_context_text or load_core_context(),
    )


def compile_exploratory_system_prompt(
    prompts: dict[str, str],
    selected_lenses: list[RankedContextItem],
    selected_footholds: list[RankedContextItem],
    core_context_text: str | None = None,
) -> str:
    return _compile_lane_system_prompt(
        prompts=prompts,
        intro_key="exploratory_system_intro",
        task_key="exploratory_task_instructions",
        output_key="exploratory_output_contract",
        selected_lenses=selected_lenses,
        selected_footholds=selected_footholds,
        core_context_text=core_context_text or load_core_context(),
    )


def compile_screening_system_prompt(prompts: dict[str, str]) -> str:
    """Backward-compatible factual prompt compilation without dynamic context injection."""
    keys = ("factual_system_intro", "factual_task_instructions", "factual_output_contract")
    parts = [str(prompts.get(key, "")).strip() for key in keys if str(prompts.get(key, "")).strip()]
    return "\n\n".join(parts).strip()


def build_screening_user_message(request: LLMScreeningRequest) -> str:
    """Build the factual user message that carries the reduced request JSON."""
    return f"SCREENING_INPUT_JSON:\n{serialize_llm_screening_request(request)}"


def build_exploratory_screening_user_message(request: ExploratoryLLMScreeningRequest) -> str:
    """Build the exploratory user message that carries the reduced request JSON."""
    return f"EXPLORATORY_SCREENING_INPUT_JSON:\n{serialize_exploratory_llm_screening_request(request)}"


def parse_raw_factual_screening_output(data: Any) -> dict[str, Any]:
    """Leniently parse a factual screening object before normalization."""
    if not isinstance(data, dict):
        raise ValueError("factual screening output must be a JSON object")
    parsed = {
        "factual_summary": _require_string(data, "factual_summary"),
        "what_is_changing": _require_string(data, "what_is_changing"),
        "actors_and_sectors": _require_optional_string(data, "actors_and_sectors"),
        "actor_groups": data.get("actor_groups", []),
        "opgave_relevance": _require_string(data, "opgave_relevance"),
        "relevance_reasons": data.get("relevance_reasons", []),
        "footholds": data.get("footholds", []),
        "evidence_quotes": data.get("evidence_quotes", []),
        "uncertainties": data.get("uncertainties", []),
        "opgave_signal_score": data.get("opgave_signal_score"),
        "rvo_link_path": data.get("rvo_link_path"),
        "score_defense": data.get("score_defense"),
        "confidence": data.get("confidence"),
    }
    if not isinstance(parsed["evidence_quotes"], list):
        raise ValueError("evidence_quotes must be a list")
    if not isinstance(parsed["opgave_signal_score"], int):
        raise ValueError("opgave_signal_score must be an integer")
    if not isinstance(parsed["confidence"], (int, float)):
        raise ValueError("confidence must be a number")
    return parsed


def normalize_factual_screening_output(raw: dict[str, Any]) -> NormalizedFactualResult:
    """Normalize factual output, repairing narrow issues and collecting warnings."""
    warnings: list[str] = []
    repairs: list[str] = []
    known_foothold_ids = _known_foothold_ids()

    evidence_quotes = _coerce_string_list(raw.get("evidence_quotes"), max_items=4)
    if len(evidence_quotes) < 2:
        raise ValueError("factual evidence_quotes must contain at least 2 usable strings")
    if len(evidence_quotes) != len(_coerce_string_list(raw.get("evidence_quotes"), max_items=999)):
        warnings.append("Overtollige of lege evidence quotes verwijderd.")
        repairs.append("trimmed_evidence_quotes")

    uncertainties = _coerce_string_list(raw.get("uncertainties"), max_items=3)
    if isinstance(raw.get("uncertainties"), list) and len(raw.get("uncertainties", [])) > len(uncertainties):
        warnings.append("Onzekerheden zijn opgeschoond of afgekapt tot maximaal 3 items.")
        repairs.append("trimmed_uncertainties")

    actor_groups = _normalize_actor_groups(raw.get("actor_groups"), warnings, repairs)
    relevance_reasons = _normalize_relevance_reasons(raw.get("relevance_reasons"), warnings, repairs)
    if not relevance_reasons:
        fallback_reason = _build_fallback_relevance_reason(raw.get("opgave_relevance"))
        if fallback_reason:
            relevance_reasons = [fallback_reason]
            warnings.append("relevance_reasons ontbraken en zijn afgeleid uit opgave_relevance.")
            repairs.append("derived_relevance_reasons")

    footholds: list[FactualFoothold] = []
    raw_footholds = raw.get("footholds")
    if raw_footholds is None:
        raw_footholds = []
    if not isinstance(raw_footholds, list):
        warnings.append("Footholds hadden een ongeldige vorm en zijn vervangen door een lege lijst.")
        repairs.append("coerced_footholds_to_empty")
        raw_footholds = []
    for item in raw_footholds[:3]:
        if not isinstance(item, dict):
            warnings.append("Een ongeldig foothold-item is verwijderd.")
            repairs.append("dropped_invalid_foothold_shape")
            continue
        foothold_id = _string_or_empty(item.get("id"))
        rationale = _string_or_empty(item.get("rationale"))
        if not foothold_id or foothold_id not in known_foothold_ids:
            warnings.append(f"Ongeldig foothold-id verwijderd: {foothold_id or 'leeg'}.")
            repairs.append("dropped_invalid_factual_foothold_id")
            continue
        if not rationale:
            warnings.append(f"Foothold zonder rationale verwijderd: {foothold_id}.")
            repairs.append("dropped_factual_foothold_without_rationale")
            continue
        footholds.append(FactualFoothold(id=foothold_id, rationale=rationale))
    if len(raw_footholds) > 3:
        warnings.append("Footholds zijn afgekapt tot maximaal 3 items.")
        repairs.append("trimmed_factual_footholds")
    if raw_footholds and not footholds:
        warnings.append("Alle factual footholds waren ongeldig en zijn verwijderd.")
        repairs.append("emptied_invalid_factual_footholds")

    score = int(raw["opgave_signal_score"])
    if score < 0 or score > 10:
        raise ValueError("opgave_signal_score must be between 0 and 10")
    confidence = float(raw["confidence"])
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("confidence must be between 0 and 1")

    rvo_link_path = _coerce_enum_value(
        raw.get("rvo_link_path"),
        ("direct_operational", "mixed", "strategic_indirect", "weak"),
    )
    if not rvo_link_path:
        rvo_link_path = _derive_rvo_link_path(score=score, foothold_count=len(footholds))
        warnings.append("rvo_link_path ontbrak of was ongeldig en is afgeleid uit score en footholds.")
        repairs.append("derived_rvo_link_path")

    score_defense = _string_or_empty(raw.get("score_defense"))
    if not score_defense:
        score_defense = _derive_score_defense(score=score, rvo_link_path=rvo_link_path)
        warnings.append("score_defense ontbrak en is automatisch aangevuld.")
        repairs.append("derived_score_defense")

    return NormalizedFactualResult(
        output=FactualScreeningOutput(
            factual_summary=_string_or_empty(raw["factual_summary"]),
            what_is_changing=_string_or_empty(raw["what_is_changing"]),
            actors_and_sectors=_string_or_empty(raw["actors_and_sectors"]),
            actor_groups=actor_groups,
            opgave_relevance=_string_or_empty(raw["opgave_relevance"]),
            relevance_reasons=relevance_reasons,
            footholds=footholds,
            evidence_quotes=evidence_quotes,
            uncertainties=uncertainties,
            opgave_signal_score=score,
            rvo_link_path=rvo_link_path,
            score_defense=score_defense,
            confidence=confidence,
        ),
        warnings=_dedupe_preserve_order(warnings),
        repairs_applied=_dedupe_preserve_order(repairs),
    )


def validate_factual_screening_output(data: Any) -> FactualScreeningOutput:
    """Backward-compatible factual validation returning canonical output only."""
    return normalize_factual_screening_output(parse_raw_factual_screening_output(data)).output


def parse_raw_exploratory_screening_output(data: Any) -> dict[str, Any]:
    """Leniently parse an exploratory screening object before normalization."""
    if not isinstance(data, dict):
        raise ValueError("exploratory screening output must be a JSON object")
    return {
        "exploration_decision": data.get("exploration_decision"),
        "decision_rationale": data.get("decision_rationale"),
        "strategic_memo": _require_string(data, "strategic_memo"),
        "hypotheses": data.get("hypotheses", []),
    }


def normalize_exploratory_screening_output(
    raw: dict[str, Any],
    factual_output: FactualScreeningOutput,
) -> NormalizedExploratoryResult:
    """Normalize exploratory output, repair narrow issues, and apply restraint heuristics."""
    warnings: list[str] = []
    repairs: list[str] = []
    known_foothold_ids = _known_foothold_ids()
    decision = _coerce_enum_value(raw.get("exploration_decision"), ("analyze", "not_needed"))
    hypotheses_raw = raw.get("hypotheses")
    if not isinstance(hypotheses_raw, list):
        warnings.append("Hypotheses hadden een ongeldige vorm en zijn vervangen door een lege lijst.")
        repairs.append("coerced_hypotheses_to_empty")
        hypotheses_raw = []
    if not decision:
        decision = "analyze" if hypotheses_raw else "not_needed"
        warnings.append("exploration_decision ontbrak of was ongeldig en is afgeleid uit het aantal hypotheses.")
        repairs.append("derived_exploration_decision")

    decision_rationale = _string_or_empty(raw.get("decision_rationale"))
    if not decision_rationale:
        decision_rationale = _default_decision_rationale(decision, factual_output)
        warnings.append("decision_rationale ontbrak en is automatisch aangevuld.")
        repairs.append("derived_decision_rationale")

    cleaned_hypotheses: list[ExploratoryHypothesis] = []
    for raw_hypothesis in hypotheses_raw:
        normalized_hypothesis = _normalize_single_hypothesis(
            raw_hypothesis,
            factual_output=factual_output,
            known_foothold_ids=known_foothold_ids,
            warnings=warnings,
            repairs=repairs,
        )
        if normalized_hypothesis:
            cleaned_hypotheses.append(normalized_hypothesis)

    if decision == "not_needed" and cleaned_hypotheses:
        cleaned_hypotheses = []
        warnings.append("Hypotheses verwijderd omdat exploration_decision op not_needed staat.")
        repairs.append("cleared_hypotheses_for_not_needed")

    if factual_output.rvo_link_path == "weak":
        if decision != "not_needed" or cleaned_hypotheses:
            warnings.append("Exploratory output omgezet naar not_needed omdat de factual RVO-link weak is.")
            repairs.append("forced_not_needed_for_weak_rvo_link")
        decision = "not_needed"
        cleaned_hypotheses = []

    max_hypotheses = _exploratory_hypothesis_cap(factual_output)
    if cleaned_hypotheses and len(cleaned_hypotheses) > max_hypotheses:
        cleaned_hypotheses = cleaned_hypotheses[:max_hypotheses]
        warnings.append(f"Exploratory hypotheses afgekapt tot {max_hypotheses} op basis van factual sterkte.")
        repairs.append("capped_exploratory_hypotheses")

    if decision == "analyze" and not cleaned_hypotheses:
        decision = "not_needed"
        if not decision_rationale:
            decision_rationale = _default_decision_rationale(decision, factual_output)
        warnings.append("Exploratory output omgezet naar not_needed omdat geen houdbare hypotheses overbleven.")
        repairs.append("converted_empty_analyze_to_not_needed")

    return NormalizedExploratoryResult(
        output=ExploratoryScreeningOutput(
            exploration_decision=decision,
            decision_rationale=decision_rationale,
            strategic_memo=_string_or_empty(raw["strategic_memo"]),
            hypotheses=cleaned_hypotheses if decision == "analyze" else [],
        ),
        warnings=_dedupe_preserve_order(warnings),
        repairs_applied=_dedupe_preserve_order(repairs),
    )


def validate_exploratory_screening_output(
    data: Any,
    allowed_evidence_refs: Optional[set[str]] = None,
) -> ExploratoryScreeningOutput:
    """Backward-compatible exploratory validation returning canonical output only."""
    if allowed_evidence_refs is None:
        raise ValueError("allowed_evidence_refs is required for exploratory validation")
    evidence_quotes = [ref.replace("quote_", "quote ") for ref in sorted(allowed_evidence_refs)]
    factual_stub = FactualScreeningOutput(
        factual_summary="stub",
        what_is_changing="stub",
        actors_and_sectors="stub",
        actor_groups=[],
        opgave_relevance="stub",
        relevance_reasons=[],
        footholds=[],
        evidence_quotes=evidence_quotes,
        uncertainties=[],
        opgave_signal_score=7,
        rvo_link_path="mixed",
        score_defense="stub",
        confidence=0.5,
    )
    normalized = normalize_exploratory_screening_output(parse_raw_exploratory_screening_output(data), factual_stub)
    invalid_refs = []
    for hypothesis in normalized.output.hypotheses:
        for ref in hypothesis.evidence_refs:
            if ref not in allowed_evidence_refs:
                invalid_refs.append(ref)
    if invalid_refs:
        raise ValueError(f"invalid evidence_refs: {', '.join(sorted(set(invalid_refs)))}")
    return normalized.output


def validate_screening_output(data: Any) -> FactualScreeningOutput:
    """Backward-compatible alias for factual output validation."""
    return validate_factual_screening_output(data)


def factual_screening_output_schema() -> dict[str, Any]:
    """Return the canonical factual response schema as a plain dict for prompt/docs use."""
    return {
        "factual_summary": "string",
        "what_is_changing": "string",
        "actors_and_sectors": "string (optionele fallback voor legacy/proza)",
        "actor_groups": [{"label": "string", "role": "string"}],
        "opgave_relevance": "string",
        "relevance_reasons": [{"title": "string", "explanation": "string"}],
        "footholds": [{"id": "string", "rationale": "string"}],
        "evidence_quotes": ["string", "string"],
        "uncertainties": ["string"],
        "opgave_signal_score": "integer 0-10",
        "rvo_link_path": ["direct_operational", "mixed", "strategic_indirect", "weak"],
        "score_defense": "string",
        "confidence": "number 0-1",
    }


def exploratory_screening_output_schema() -> dict[str, Any]:
    """Return the canonical exploratory response schema."""
    return {
        "exploration_decision": ["analyze", "not_needed"],
        "decision_rationale": "string",
        "strategic_memo": "string",
        "hypotheses": [
            {
                "hypothesis": "string",
                "mechanism": "string",
                "foothold_ids": ["string"],
                "evidence_refs": ["quote_1"],
                "certainty": ["likely", "possible", "speculative"],
                "verification": "string",
            }
        ],
    }


def screening_output_schema() -> dict[str, Any]:
    """Backward-compatible alias for the factual schema."""
    return factual_screening_output_schema()


@lru_cache(maxsize=1)
def _known_foothold_ids() -> set[str]:
    return {str(item.get("id")).strip() for item in load_rvo_footholds() if str(item.get("id")).strip()}


def map_hypothesis_to_evidence_refs(
    hypothesis_text: str,
    mechanism_text: str,
    evidence_quotes: list[str],
) -> list[str]:
    """Map a hypothesis to the best matching factual quote refs using token overlap."""
    combined = f"{hypothesis_text} {mechanism_text}".strip()
    scored: list[tuple[int, str]] = []
    for index, quote in enumerate(evidence_quotes, start=1):
        overlap = _token_overlap_score(combined, quote)
        if overlap > 0:
            scored.append((overlap, f"quote_{index}"))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [ref for _, ref in scored[:2]]


def _normalize_single_hypothesis(
    raw_hypothesis: Any,
    factual_output: FactualScreeningOutput,
    known_foothold_ids: set[str],
    warnings: list[str],
    repairs: list[str],
) -> Optional[ExploratoryHypothesis]:
    if not isinstance(raw_hypothesis, dict):
        warnings.append("Een exploratory hypothese had een ongeldige vorm en is verwijderd.")
        repairs.append("dropped_invalid_hypothesis_shape")
        return None

    hypothesis_text = _string_or_empty(raw_hypothesis.get("hypothesis"))
    mechanism_text = _string_or_empty(raw_hypothesis.get("mechanism"))
    verification_text = _string_or_empty(raw_hypothesis.get("verification"))
    if not hypothesis_text or not mechanism_text or not verification_text:
        warnings.append("Een exploratory hypothese zonder verplichte tekstvelden is verwijderd.")
        repairs.append("dropped_incomplete_hypothesis")
        return None

    raw_footholds = raw_hypothesis.get("foothold_ids")
    foothold_ids = _coerce_string_list(raw_footholds, max_items=3)
    valid_footholds = [item for item in foothold_ids if item in known_foothold_ids]
    if len(valid_footholds) < len(foothold_ids):
        warnings.append("Ongeldige exploratory foothold ids zijn verwijderd.")
        repairs.append("dropped_invalid_exploratory_foothold_ids")

    evidence_refs = [
        ref
        for ref in _coerce_string_list(raw_hypothesis.get("evidence_refs"), max_items=4)
        if ref in {f"quote_{index}" for index, _ in enumerate(factual_output.evidence_quotes, start=1)}
    ]
    if not evidence_refs:
        evidence_refs = map_hypothesis_to_evidence_refs(
            hypothesis_text,
            mechanism_text,
            factual_output.evidence_quotes,
        )
        if evidence_refs:
            warnings.append("Ontbrekende of ongeldige evidence_refs zijn automatisch aangevuld.")
            repairs.append("derived_evidence_refs")
    if not evidence_refs:
        warnings.append("Een exploratory hypothese zonder bruikbare evidence_refs is verwijderd.")
        repairs.append("dropped_hypothesis_without_evidence_refs")
        return None

    strong_grounding = _has_strong_factual_grounding(hypothesis_text, mechanism_text, factual_output)
    if not valid_footholds and not strong_grounding:
        warnings.append("Een exploratory hypothese zonder foothold en zonder sterke factual grounding is verwijderd.")
        repairs.append("dropped_weakly_grounded_hypothesis")
        return None

    certainty = _coerce_enum_value(raw_hypothesis.get("certainty"), ("likely", "possible", "speculative"))
    if not certainty:
        certainty = "possible"
        warnings.append("Ongeldige certainty is vervangen door possible.")
        repairs.append("replaced_invalid_certainty")
    if certainty == "likely" and (not evidence_refs or (not valid_footholds and not strong_grounding)):
        certainty = "possible"
        warnings.append("Een likely-hypothese is afgezwakt naar possible wegens beperkte grounding.")
        repairs.append("downgraded_likely_to_possible")

    return ExploratoryHypothesis(
        hypothesis=hypothesis_text,
        mechanism=mechanism_text,
        foothold_ids=valid_footholds,
        evidence_refs=evidence_refs,
        certainty=certainty,
        verification=verification_text,
    )


def _exploratory_hypothesis_cap(factual_output: FactualScreeningOutput) -> int:
    if factual_output.rvo_link_path == "weak":
        return 0
    if factual_output.opgave_signal_score <= 5:
        return 1
    if factual_output.rvo_link_path == "strategic_indirect" and factual_output.opgave_signal_score <= 6:
        return 2
    if factual_output.opgave_signal_score >= 7 and factual_output.rvo_link_path in {"mixed", "direct_operational"}:
        return 3
    return 2


def _has_strong_factual_grounding(
    hypothesis_text: str,
    mechanism_text: str,
    factual_output: FactualScreeningOutput,
) -> bool:
    reference_text = " ".join(
        [
            factual_output.opgave_relevance,
            factual_output.score_defense,
            factual_output.actors_and_sectors,
            factual_output.what_is_changing,
        ]
    )
    return _token_overlap_score(f"{hypothesis_text} {mechanism_text}", reference_text) >= 2


def _normalize_actor_groups(raw_actor_groups: Any, warnings: list[str], repairs: list[str]) -> list[FactualActorGroup]:
    if raw_actor_groups is None:
        return []
    if not isinstance(raw_actor_groups, list):
        warnings.append("actor_groups hadden een ongeldige vorm en zijn vervangen door een lege lijst.")
        repairs.append("coerced_actor_groups_to_empty")
        return []

    actor_groups: list[FactualActorGroup] = []
    for item in raw_actor_groups[:4]:
        if not isinstance(item, dict):
            warnings.append("Een ongeldig actor_group-item is verwijderd.")
            repairs.append("dropped_invalid_actor_group_shape")
            continue
        label = _string_or_empty(item.get("label"))
        role = _string_or_empty(item.get("role"))
        if not label or not role:
            warnings.append("Een actor_group zonder label of role is verwijderd.")
            repairs.append("dropped_incomplete_actor_group")
            continue
        actor_groups.append(FactualActorGroup(label=label, role=role))
    if len(raw_actor_groups) > 4:
        warnings.append("actor_groups zijn afgekapt tot maximaal 4 items.")
        repairs.append("trimmed_actor_groups")
    return actor_groups


def _normalize_relevance_reasons(raw_reasons: Any, warnings: list[str], repairs: list[str]) -> list[FactualRelevanceReason]:
    if raw_reasons is None:
        return []
    if not isinstance(raw_reasons, list):
        warnings.append("relevance_reasons hadden een ongeldige vorm en zijn vervangen door een lege lijst.")
        repairs.append("coerced_relevance_reasons_to_empty")
        return []

    reasons: list[FactualRelevanceReason] = []
    for item in raw_reasons[:4]:
        if not isinstance(item, dict):
            warnings.append("Een ongeldig relevance_reason-item is verwijderd.")
            repairs.append("dropped_invalid_relevance_reason_shape")
            continue
        title = _string_or_empty(item.get("title"))
        explanation = _string_or_empty(item.get("explanation"))
        if not title or not explanation:
            warnings.append("Een relevance_reason zonder title of explanation is verwijderd.")
            repairs.append("dropped_incomplete_relevance_reason")
            continue
        reasons.append(FactualRelevanceReason(title=title, explanation=explanation))
    if len(raw_reasons) > 4:
        warnings.append("relevance_reasons zijn afgekapt tot maximaal 4 items.")
        repairs.append("trimmed_relevance_reasons")
    return reasons


def _build_fallback_relevance_reason(opgave_relevance: Any) -> Optional[FactualRelevanceReason]:
    explanation = _string_or_empty(opgave_relevance)
    if not explanation:
        return None
    shortened = explanation if len(explanation) <= 220 else explanation[:217].rstrip() + "..."
    return FactualRelevanceReason(
        title="Kernreden",
        explanation=shortened,
    )


def _derive_rvo_link_path(score: int, foothold_count: int) -> Literal["direct_operational", "mixed", "strategic_indirect", "weak"]:
    if foothold_count >= 2 and score >= 7:
        return "mixed"
    if foothold_count >= 1 and score >= 8:
        return "direct_operational"
    if score <= 3 and foothold_count == 0:
        return "weak"
    return "strategic_indirect"


def _derive_score_defense(score: int, rvo_link_path: str) -> str:
    mapping = {
        "direct_operational": "Deze score volgt uit een sterke inhoudelijke relevantie met een directe operationele landing voor RVO.",
        "mixed": "Deze score volgt uit een combinatie van duidelijke inhoudelijke relevantie en een plausibele praktische landing voor RVO.",
        "strategic_indirect": "Deze score volgt vooral uit strategische relevantie, terwijl de praktische landing voor RVO indirect blijft.",
        "weak": "Deze score blijft beperkt doordat zowel de inhoudelijke als praktische RVO-link zwak is.",
    }
    prefix = mapping.get(rvo_link_path, "Deze score volgt uit de gecombineerde inhoudelijke en praktische relevantie voor RVO.")
    return f"{prefix} Score: {score}/10."


def _default_decision_rationale(decision: str, factual_output: FactualScreeningOutput) -> str:
    if decision == "not_needed":
        return "De factual analyse biedt al voldoende strategische duiding voor dit document."
    return f"Er blijft aanvullende strategische verkenning mogelijk bovenop de factual analyse ({factual_output.rvo_link_path}, score {factual_output.opgave_signal_score}/10)."


def _coerce_string_list(value: Any, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _coerce_enum_value(value: Any, allowed: tuple[str, ...]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized in allowed else None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _token_overlap_score(left: str, right: str) -> int:
    left_tokens = set(_meaningful_tokens(left))
    right_tokens = set(_meaningful_tokens(right))
    return len(left_tokens & right_tokens)


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]+", (text or "").lower())
        if len(token) >= 5
    ]


def _compile_lane_system_prompt(
    prompts: dict[str, str],
    intro_key: str,
    task_key: str,
    output_key: str,
    selected_lenses: list[RankedContextItem],
    selected_footholds: list[RankedContextItem],
    core_context_text: str,
) -> str:
    parts = [
        str(prompts.get(intro_key, "")).strip(),
        format_context_block(
            core_context=core_context_text,
            selected_lenses=selected_lenses,
            selected_footholds=selected_footholds,
        ),
        str(prompts.get(task_key, "")).strip(),
        str(prompts.get(output_key, "")).strip(),
    ]
    return "\n\n".join([part for part in parts if part]).strip()


def _build_html_excerpt(article_text: str, title: str) -> tuple[str, str]:
    paragraphs = _prepare_html_paragraphs(article_text, title)
    selected = take_paragraphs_by_word_budget(
        paragraphs,
        target_words=HTML_TARGET_WORDS,
        max_words=HTML_MAX_WORDS,
        max_chars=HTML_MAX_CHARS,
    )
    return "html_lead", "\n\n".join(selected).strip()


def _build_html_with_pdf_excerpt(
    article_text: str,
    pdf_text: str,
    keyword_tags: list[str],
    title: str,
) -> tuple[str, str]:
    pdf_budget = _resolve_pdf_budget(pdf_text)
    article_paragraphs = _prepare_html_paragraphs(article_text, title)
    article_selected = take_paragraphs_by_word_budget(
        article_paragraphs,
        target_words=HTML_WITH_PDF_ARTICLE_TARGET_WORDS,
        max_words=HTML_WITH_PDF_ARTICLE_MAX_WORDS,
        max_chars=pdf_budget["html_total_max_chars"],
    )
    article_excerpt = "\n\n".join(article_selected).strip()
    article_words = count_words(article_excerpt)

    if article_words >= HTML_WITH_PDF_SHORT_THRESHOLD_WORDS:
        return "html_lead", article_excerpt

    remaining_words = max(0, pdf_budget["html_total_max_words"] - article_words)
    if remaining_words <= 0:
        return "html_lead", article_excerpt

    pdf_selected, pdf_strategy = _select_pdf_excerpt_paragraphs(
        pdf_text,
        keyword_tags,
        long_pdf=pdf_budget["is_long_pdf"],
        max_words=remaining_words,
        max_chars=max(0, pdf_budget["html_total_max_chars"] - len(article_excerpt)),
    )
    pdf_excerpt = "\n\n".join(pdf_selected).strip()
    if not pdf_excerpt:
        return "html_lead", article_excerpt

    parts = [f"ARTICLE_EXCERPT:\n{article_excerpt}".strip(), f"PDF_EXCERPT:\n{pdf_excerpt}".strip()]
    strategy = "html_lead_plus_pdf_summary_section" if pdf_strategy.startswith("pdf_heading") else "html_lead_plus_pdf_signal"
    return strategy, "\n\n".join([part for part in parts if part]).strip()


def _build_pdf_excerpt(pdf_text: str, keyword_tags: list[str], title: str) -> tuple[str, str]:
    pdf_budget = _resolve_pdf_budget(pdf_text)
    selected, strategy = _select_pdf_excerpt_paragraphs(
        pdf_text,
        keyword_tags,
        title=title,
        long_pdf=pdf_budget["is_long_pdf"],
        target_words=pdf_budget["target_words"],
        max_words=pdf_budget["max_words"],
        max_chars=pdf_budget["max_chars"],
    )
    return strategy, "\n\n".join(selected).strip()


def _select_pdf_excerpt_paragraphs(
    pdf_text: str,
    keyword_tags: list[str],
    title: str = "",
    target_words: int = PDF_TOTAL_TARGET_WORDS,
    max_words: int = PDF_TOTAL_MAX_WORDS,
    max_chars: int = PDF_TOTAL_MAX_CHARS,
    long_pdf: bool = False,
) -> tuple[list[str], str]:
    raw_paragraphs = extract_cleaned_paragraphs(pdf_text)
    heading_indexes = find_heading_like_paragraphs(raw_paragraphs)
    paragraphs = filter_substantive_paragraphs(raw_paragraphs, title=title)
    selected_indexes: set[int] = set()
    selected: list[str] = []

    if heading_indexes:
        tier1 = collect_post_heading_paragraphs(
            raw_paragraphs,
            heading_indexes,
            max_following=PDF_POST_HEADING_WINDOW,
            target_words=LONG_PDF_TIER1_TARGET_WORDS if long_pdf else PDF_TIER1_TARGET_WORDS,
            max_words=LONG_PDF_TIER1_MAX_WORDS if long_pdf else PDF_TIER1_MAX_WORDS,
            max_chars=max_chars,
            title=title,
        )
        for index, paragraph in tier1:
            if index in selected_indexes:
                continue
            selected_indexes.add(index)
            selected.append(paragraph)

    tier1_has_keyword_signal = any(paragraph_keyword_score(paragraph, keyword_tags) > 0 for paragraph in selected)

    used_words = count_words("\n\n".join(selected))
    used_chars = len("\n\n".join(selected))
    remaining_words = max(0, max_words - used_words)
    remaining_chars = max(0, max_chars - used_chars)
    target_remaining_words = max(0, target_words - used_words)

    scored = [
        (index, paragraph, paragraph_keyword_score(paragraph, keyword_tags))
        for index, paragraph in enumerate(raw_paragraphs)
        if index not in selected_indexes and paragraph in paragraphs
    ]
    hits = [row for row in scored if row[2] > 0]
    if hits:
        top_hits = sorted(hits, key=lambda row: (-row[2], row[0]))
        ordered = [row[1] for row in sorted(top_hits, key=lambda row: row[0])]
        keyword_selected = take_paragraphs_by_word_budget(
            ordered,
            target_words=target_remaining_words or remaining_words,
            max_words=remaining_words,
            max_chars=remaining_chars,
        )
        selected.extend(keyword_selected)
        strategy = "pdf_heading_plus_keyword" if heading_indexes and selected_indexes else "pdf_keyword_windows"
        return selected, strategy

    fallback = [row[1] for row in scored]
    fallback_selected = take_paragraphs_by_word_budget(
        fallback,
        target_words=target_remaining_words or remaining_words,
        max_words=remaining_words,
        max_chars=remaining_chars,
    )
    selected.extend(fallback_selected)
    if heading_indexes and selected_indexes:
        strategy = "pdf_heading_plus_keyword" if tier1_has_keyword_signal else "pdf_heading_plus_fallback"
    else:
        strategy = "pdf_front_matter_fallback"
    return selected, strategy


def count_words(text: str) -> int:
    """Count words using a simple whitespace/token regex."""
    return len(re.findall(r"\b\S+\b", text or ""))


def _resolve_pdf_budget(pdf_text: str) -> dict[str, int | bool]:
    pdf_words = count_words(pdf_text)
    is_long_pdf = pdf_words > LONG_PDF_THRESHOLD_WORDS
    return {
        "is_long_pdf": is_long_pdf,
        "target_words": LONG_PDF_TOTAL_TARGET_WORDS if is_long_pdf else PDF_TOTAL_TARGET_WORDS,
        "max_words": LONG_PDF_TOTAL_MAX_WORDS if is_long_pdf else PDF_TOTAL_MAX_WORDS,
        "max_chars": LONG_PDF_TOTAL_MAX_CHARS if is_long_pdf else PDF_TOTAL_MAX_CHARS,
        "html_total_max_words": HTML_WITH_PDF_LONG_TOTAL_MAX_WORDS if is_long_pdf else HTML_WITH_PDF_TOTAL_MAX_WORDS,
        "html_total_max_chars": HTML_WITH_PDF_LONG_TOTAL_MAX_CHARS if is_long_pdf else HTML_WITH_PDF_TOTAL_MAX_CHARS,
    }


def take_paragraphs_by_word_budget(
    paragraphs: list[str],
    target_words: int,
    max_words: int,
    max_chars: int,
) -> list[str]:
    paragraphs = _expand_oversized_paragraphs_for_budget(paragraphs, max_words=max_words, max_chars=max_chars)
    selected: list[str] = []
    for paragraph in paragraphs:
        candidate = selected + [paragraph]
        candidate_text = "\n\n".join(candidate)
        candidate_words = count_words(candidate_text)
        if selected and (candidate_words > max_words or len(candidate_text) > max_chars):
            break
        selected.append(paragraph)
        selected_text = "\n\n".join(selected)
        if count_words(selected_text) >= target_words:
            break
    return selected


def _expand_oversized_paragraphs_for_budget(
    paragraphs: list[str],
    max_words: int,
    max_chars: int,
) -> list[str]:
    expanded: list[str] = []
    for paragraph in paragraphs:
        if (
            count_words(paragraph) > SENTENCE_GROUP_MAX_WORDS
            or count_words(paragraph) > max_words
            or len(paragraph) > max_chars
        ):
            expanded.extend(_split_paragraph_into_sentence_groups(paragraph))
        else:
            expanded.append(paragraph)
    return expanded


def find_heading_like_paragraphs(paragraphs: list[str]) -> list[int]:
    """Return indexes of short heading-like paragraphs that match the canonical list."""
    indexes: list[int] = []
    for index, paragraph in enumerate(paragraphs):
        normalized = _normalize_heading(paragraph)
        if not normalized:
            continue
        if count_words(normalized) > 4 or len(normalized) > 50:
            continue
        if any(normalized == heading or normalized.startswith(f"{heading} ") for heading in CANONICAL_PDF_HEADINGS):
            indexes.append(index)
    return indexes


def collect_post_heading_paragraphs(
    paragraphs: list[str],
    heading_indexes: list[int],
    max_following: int,
    target_words: int,
    max_words: int,
    max_chars: int,
    title: str = "",
) -> list[tuple[int, str]]:
    """Collect paragraphs immediately following matched headings within a reserved budget."""
    heading_set = set(heading_indexes)
    selected_rows: list[tuple[int, str]] = []
    selected_indexes: set[int] = set()
    title_norm = _normalize_compare_text(title or "")

    for heading_index in heading_indexes:
        collected = 0
        cursor = heading_index + 1
        while cursor < len(paragraphs) and collected < max_following:
            if cursor in heading_set:
                break
            paragraph = paragraphs[cursor]
            if cursor in selected_indexes:
                cursor += 1
                continue
            candidate_paragraph = re.sub(r"\s+", " ", paragraph).strip()
            if not candidate_paragraph:
                cursor += 1
                continue
            if title_norm and _normalize_compare_text(candidate_paragraph) == title_norm:
                cursor += 1
                continue
            if _looks_like_source_date_prefix(candidate_paragraph):
                cursor += 1
                continue
            if _is_page_number_line(candidate_paragraph):
                cursor += 1
                continue
            if len(candidate_paragraph) < MIN_SUBSTANTIVE_CHARS and len(candidate_paragraph.split()) < MIN_SUBSTANTIVE_WORDS:
                cursor += 1
                continue
            candidate_rows = selected_rows + [(cursor, paragraph)]
            candidate_text = "\n\n".join(row[1] for row in candidate_rows)
            if selected_rows and (count_words(candidate_text) > max_words or len(candidate_text) > max_chars):
                return selected_rows
            selected_rows.append((cursor, candidate_paragraph))
            selected_indexes.add(cursor)
            collected += 1
            if count_words(candidate_text) >= target_words:
                return selected_rows
            cursor += 1

    return selected_rows


def _clean_html_text(text: str) -> str:
    lines = _normalize_lines(text)
    if not lines:
        return ""

    paragraphs = _html_lines_to_paragraphs(lines)
    paragraphs = _strip_html_top_noise(paragraphs)
    return _normalize_paragraphs(paragraphs)


def _clean_pdf_text(text: str) -> str:
    lines = _normalize_lines(text)
    if not lines:
        return ""

    lines = _drop_repeated_short_lines(lines)

    paragraphs: list[str] = []
    current: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(_join_pdf_paragraph(current))
                current = []
            continue
        if _is_page_number_line(line) or _looks_like_toc_artifact(line):
            continue
        current.append(line)

    if current:
        paragraphs.append(_join_pdf_paragraph(current))

    paragraphs = _split_heading_prefixed_paragraphs(paragraphs)
    return _normalize_paragraphs(paragraphs)


def _normalize_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _normalize_mojibake_variants(normalized)
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return [line.rstrip() for line in normalized.split("\n")]


def _normalize_mojibake_variants(text: str) -> str:
    replacements = {
        "\u00c2\u00b7": ".",
        "\u00e2\u20ac\u00a2": "-",
        "\u2022": "-",
        "\u00b7": ".",
    }
    normalized = text
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def _lines_to_paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current).strip())
    return paragraphs


def _html_lines_to_paragraphs(lines: list[str]) -> list[str]:
    """
    Preserve more HTML structure than the generic line joiner.

    BeautifulSoup extraction in fetcher uses newline separators between many
    block elements. If we merge all non-empty lines until a blank line, whole
    articles often collapse into one paragraph. Here we keep most non-empty
    lines as their own paragraphs and only join lines that look like wrapped
    continuations.
    """
    paragraphs: list[str] = []
    current = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(current.strip())
                current = ""
            continue

        if not current:
            current = line
            continue

        if _should_join_html_lines(current, line):
            current = f"{current} {line}".strip()
        else:
            paragraphs.append(current.strip())
            current = line

    if current:
        paragraphs.append(current.strip())
    return paragraphs


def _prepare_html_paragraphs(article_text: str, title: str) -> list[str]:
    paragraphs = filter_substantive_paragraphs(extract_cleaned_paragraphs(article_text), title=title)
    if len(paragraphs) == 1 and count_words(paragraphs[0]) > SENTENCE_GROUP_MAX_WORDS:
        return _split_paragraph_into_sentence_groups(paragraphs[0])
    return paragraphs


def _normalize_paragraphs(paragraphs: list[str]) -> str:
    cleaned = []
    for paragraph in paragraphs:
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized:
            cleaned.append(normalized)
    return "\n\n".join(cleaned).strip()


def _strip_html_top_noise(paragraphs: list[str]) -> list[str]:
    if not paragraphs:
        return []

    cleaned: list[str] = []
    seen_top_values: set[str] = set()
    body_started = False
    kept_title_like = False

    for index, paragraph in enumerate(paragraphs):
        candidate = paragraph.strip()
        if not candidate:
            continue

        normalized = _normalize_compare_text(candidate)
        is_duplicate_top = normalized in seen_top_values
        seen_top_values.add(normalized)

        if not body_started:
            if is_duplicate_top:
                continue
            if _looks_like_source_date_prefix(candidate):
                continue
            if _looks_like_short_html_boilerplate(candidate):
                continue
            if not kept_title_like and _looks_like_title_only(candidate):
                cleaned.append(candidate)
                kept_title_like = True
                continue
            body_started = True

        cleaned.append(candidate)

    return cleaned


def _should_join_html_lines(previous: str, current: str) -> bool:
    previous = previous.strip()
    current = current.strip()
    if not previous or not current:
        return False

    if previous.endswith("-"):
        return True

    # Treat obviously wrapped continuation lines as part of the same paragraph.
    if not re.search(r"[.!?:\"]$", previous) and current[:1].islower():
        return True

    # Very short label-like lines that flow directly into a sentence.
    if len(previous) <= 40 and previous.endswith(":"):
        return True

    return False


def _split_paragraph_into_sentence_groups(paragraph: str) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return [paragraph]

    groups: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join(current + [sentence]).strip()
        candidate_words = count_words(candidate)
        if current and candidate_words > SENTENCE_GROUP_MAX_WORDS:
            groups.append(" ".join(current).strip())
            current = [sentence]
            continue
        current.append(sentence)
        if candidate_words >= SENTENCE_GROUP_MIN_WORDS:
            groups.append(" ".join(current).strip())
            current = []
    if current:
        groups.append(" ".join(current).strip())
    return groups or [paragraph]


def _looks_like_short_html_boilerplate(text: str) -> bool:
    lowered = text.lower().strip()
    if len(text) > 80:
        return False
    markers = (
        "lees voor",
        "deel via",
        "print",
        "naar inhoud",
        "ga direct naar",
        "hoofdnavigatie",
    )
    return any(marker in lowered for marker in markers)


def _looks_like_title_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "|" in stripped:
        return False
    if stripped.endswith((".", "!", "?", ":")):
        return False
    words = stripped.split()
    return 1 <= len(words) <= 12 and len(stripped) <= 120


def _looks_like_source_date_prefix(text: str) -> bool:
    if len(text.strip()) > 140:
        return False
    lowered = text.lower()
    if "|" not in lowered:
        return False
    prefix_markers = (
        "nieuwsbericht",
        "kamerbrief",
        "kamerstuk",
        "publicatie",
        "rapport",
        "speech",
        "besluit",
    )
    has_marker = any(marker in lowered for marker in prefix_markers)
    has_date = bool(
        re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", text)
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    )
    return has_marker and has_date


def _is_page_number_line(text: str) -> bool:
    compact = text.strip().lower()
    if not compact:
        return False
    if re.fullmatch(r"\d{1,4}", compact):
        return True
    if re.fullmatch(r"page\s+\d{1,4}", compact):
        return True
    if re.fullmatch(r"pagina\s+\d{1,4}", compact):
        return True
    if re.fullmatch(r"\d{1,4}\s*/\s*\d{1,4}", compact):
        return True
    return False


def _looks_like_toc_artifact(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 160:
        return False
    return bool(re.search(r"[.]{4,}\s*\d{1,4}$", stripped))


def _split_heading_prefixed_paragraphs(paragraphs: list[str]) -> list[str]:
    """
    Preserve PDF summary/conclusion headings as standalone paragraphs.

    PDF extraction often merges a heading like "Samenvatting" with the first
    sentence of the following paragraph. Splitting that prefix back out makes
    the tier-1 heading detector reliable on long reports.
    """
    split_paragraphs: list[str] = []
    heading_pattern = _build_heading_prefix_pattern()

    for paragraph in paragraphs:
        candidate = paragraph.strip()
        if not candidate:
            continue

        match = heading_pattern.match(candidate)
        if not match:
            split_paragraphs.append(candidate)
            continue

        heading = match.group("heading").strip()
        rest = match.group("rest").strip()

        # Only split when there is clearly body text following the heading.
        if rest and count_words(rest) >= MIN_SUBSTANTIVE_WORDS:
            split_paragraphs.append(heading)
            split_paragraphs.append(rest)
        else:
            split_paragraphs.append(candidate)

    return split_paragraphs


def _drop_repeated_short_lines(lines: list[str]) -> list[str]:
    meaningful_lines = [line.strip() for line in lines if line.strip()]
    counts = Counter(meaningful_lines)
    repeated = {
        line
        for line, count in counts.items()
        if count >= 3 and 0 < len(line) <= 80 and not _is_page_number_line(line)
    }
    return [line for line in lines if line.strip() not in repeated]


def _join_pdf_paragraph(lines: list[str]) -> str:
    if not lines:
        return ""

    paragraph = lines[0]
    for line in lines[1:]:
        previous = paragraph.rstrip()
        current = line.lstrip()
        if _should_keep_hard_break(previous, current):
            paragraph = f"{previous}\n{current}"
        else:
            paragraph = f"{previous} {current}"

    paragraph = paragraph.replace("\n", " ")
    paragraph = re.sub(r"\s+", " ", paragraph)
    paragraph = re.sub(r"(\w)-\s+(\w)", r"\1\2", paragraph)
    return paragraph.strip()


def _should_keep_hard_break(previous: str, current: str) -> bool:
    if previous.endswith(":"):
        return True
    if re.match(r"^[-*]\s+", current):
        return True
    if re.match(r"^\d+[.)]\s+", current):
        return True
    if previous.isupper() and len(previous) <= 80:
        return True
    return False


def _parse_keyword_tags(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item).strip().lower() for item in raw_value if str(item).strip()]
    try:
        parsed = json.loads(str(raw_value))
        if isinstance(parsed, list):
            return [str(item).strip().lower() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return []


def _format_publication_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _get_document_value(document: Any, key: str) -> Any:
    if isinstance(document, dict):
        return document.get(key)
    return getattr(document, key, None)


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_or_empty(value: Any) -> str:
    return _string_or_none(value) or ""


def _normalize_compare_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _normalize_heading(text: str) -> str:
    normalized = _normalize_compare_text(text)
    normalized = normalized.rstrip(":")
    return normalized


def _build_heading_prefix_pattern() -> re.Pattern[str]:
    escaped = "|".join(re.escape(heading) for heading in CANONICAL_PDF_HEADINGS)
    return re.compile(
        rf"^(?P<heading>(?:{escaped}))[:\s]+(?P<rest>.+)$",
        flags=re.IGNORECASE,
    )


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _require_optional_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def _require_string_list(
    data: dict[str, Any],
    key: str,
    min_items: int,
    max_items: int,
) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if len(value) < min_items or len(value) > max_items:
        raise ValueError(f"{key} must contain between {min_items} and {max_items} items")

    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} must contain only non-empty strings")
        normalized = item.strip()
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def _require_int_in_range(
    data: dict[str, Any],
    key: str,
    min_value: int,
    max_value: int,
) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(f"{key} must be between {min_value} and {max_value}")
    return value


def _require_float_in_range(
    data: dict[str, Any],
    key: str,
    min_value: float,
    max_value: float,
) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    numeric = float(value)
    if numeric < min_value or numeric > max_value:
        raise ValueError(f"{key} must be between {min_value} and {max_value}")
    return numeric


def _require_enum_value(value: Any, allowed: tuple[str, ...], key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    normalized = value.strip()
    if normalized not in allowed:
        raise ValueError(f"{key} must be one of {allowed}")
    return normalized


def _require_enum_list(data: dict[str, Any], key: str, allowed: tuple[str, ...]) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    cleaned: list[str] = []
    for item in value:
        normalized = _require_enum_value(item, allowed, key)
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned

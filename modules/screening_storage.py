"""
Helpers for parsing stored screening JSON across dashboard and tests.
"""

from __future__ import annotations

import json


def parse_json_object(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def parse_factual_screening_output(raw: str | None) -> dict | None:
    data = parse_json_object(raw)
    if not data:
        return None

    if "factual_summary" in data and "opgave_relevance" in data:
        data.setdefault("actor_groups", [])
        data.setdefault("relevance_reasons", [])
        data.setdefault("rvo_link_path", None)
        data.setdefault("score_defense", "")
        return data

    if "short_summary" in data and "climate_adaptation_explanation" in data:
        return {
            "factual_summary": data.get("short_summary", ""),
            "what_is_changing": "",
            "actors_and_sectors": "",
            "actor_groups": [],
            "opgave_relevance": data.get("climate_adaptation_explanation", ""),
            "relevance_reasons": [],
            "footholds": [],
            "evidence_quotes": [],
            "uncertainties": [],
            "opgave_signal_score": data.get("climate_adaptation_relevance_score"),
            "rvo_link_path": None,
            "score_defense": "",
            "confidence": data.get("confidence"),
            "_legacy": True,
            "_legacy_cross_domain_relevance_signal": data.get("cross_domain_relevance_signal"),
            "_legacy_cross_domain_explanation": data.get("cross_domain_explanation"),
        }

    return None


def parse_exploratory_screening_output(raw: str | None) -> dict | None:
    data = parse_json_object(raw)
    if not data:
        return None
    if "strategic_memo" in data and isinstance(data.get("hypotheses"), list):
        data.setdefault("exploration_decision", "analyze")
        data.setdefault("decision_rationale", "")
        return data
    return None


def parse_screening_context(raw: str | None) -> dict | None:
    data = parse_json_object(raw)
    if not data:
        return None
    if "core_context_version" not in data:
        return None
    return data

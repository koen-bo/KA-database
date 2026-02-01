"""
Climate Adaptation Knowledge Base - Tiered Relevance Filter

Implements a two-tier keyword filtering system:
- Tier 1: Direct hit keywords → Always download
- Tier 2: Context keywords → Only download if combined with context words

This prevents downloading every document about general topics like
"woningbouw" or "landbouw" while still catching relevant climate docs.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class FilterResult:
    """Result of the relevance filter check."""
    is_relevant: bool
    tier: Optional[int]  # 1, 2, or None if not relevant
    matched_keywords: list[str]
    matched_context: list[str]  # For Tier 2 matches
    theme: Optional[str]  # For Tier 2, which theme matched


def check_relevance(title: str, description: str = "") -> FilterResult:
    """
    Check if an RSS item is relevant using the tiered keyword system.
    
    Tier 1: If any Tier 1 keyword is found → Relevant (always download)
    Tier 2: If any Tier 2 keyword is found AND a context word → Relevant
    
    Args:
        title: The RSS item title
        description: The RSS item description/summary (optional)
    
    Returns:
        FilterResult with details about the match
    """
    text = f"{title} {description}".lower()
    
    # Check Tier 1 first (direct hits)
    tier1_keywords = config.load_tier1_keywords()
    tier1_matches = [kw for kw in tier1_keywords if kw in text]
    
    if tier1_matches:
        return FilterResult(
            is_relevant=True,
            tier=1,
            matched_keywords=tier1_matches,
            matched_context=[],
            theme=None
        )
    
    # Check Tier 2 (context-dependent)
    context_words = config.load_context_words()
    context_matches = [w for w in context_words if w in text]
    
    # Load Tier 2 themes fresh from file
    tier2_themes = config.load_tier2_themes()
    
    # Only check Tier 2 if we have context
    if context_matches:
        for theme, keywords in tier2_themes.items():
            theme_matches = [kw for kw in keywords if kw in text]
            if theme_matches:
                return FilterResult(
                    is_relevant=True,
                    tier=2,
                    matched_keywords=theme_matches,
                    matched_context=context_matches,
                    theme=theme
                )
    
    # Also check if multiple Tier 2 keywords from different themes appear together
    # (they provide context for each other)
    all_tier2_matches = []
    matched_themes = set()
    for theme, keywords in tier2_themes.items():
        for kw in keywords:
            if kw in text:
                all_tier2_matches.append(kw)
                matched_themes.add(theme)
    
    # If we have Tier 2 matches from 2+ different themes, consider it relevant
    if len(matched_themes) >= 2:
        return FilterResult(
            is_relevant=True,
            tier=2,
            matched_keywords=all_tier2_matches,
            matched_context=["(multi-theme match)"],
            theme=", ".join(matched_themes)
        )
    
    # Not relevant
    return FilterResult(
        is_relevant=False,
        tier=None,
        matched_keywords=[],
        matched_context=[],
        theme=None
    )


def is_relevant(title: str, description: str = "") -> bool:
    """
    Simple boolean check for relevance.
    
    Use check_relevance() for detailed information about the match.
    
    Args:
        title: The RSS item title
        description: The RSS item description/summary (optional)
    
    Returns:
        True if the item is relevant, False otherwise
    """
    result = check_relevance(title, description)
    return result.is_relevant


def get_matching_keywords(title: str, description: str = "") -> list[str]:
    """
    Get all matching keywords found in the RSS item.
    
    For backward compatibility with the simple filter.
    
    Args:
        title: The RSS item title
        description: The RSS item description/summary (optional)
    
    Returns:
        List of keywords that were found
    """
    result = check_relevance(title, description)
    return result.matched_keywords


def format_filter_result(result: FilterResult) -> str:
    """
    Format a FilterResult for logging/display.
    
    Args:
        result: The FilterResult to format
    
    Returns:
        Human-readable string describing the match
    """
    if not result.is_relevant:
        return "Not relevant (no keyword matches)"
    
    if result.tier == 1:
        return f"[Tier 1] Direct hit: {', '.join(result.matched_keywords[:3])}"
    
    if result.tier == 2:
        context = result.matched_context[0] if result.matched_context else ""
        return (
            f"[Tier 2] {result.theme}: "
            f"{', '.join(result.matched_keywords[:3])} + context: {context}"
        )
    
    return "Unknown match type"

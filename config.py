"""
Climate Adaptation Knowledge Base - Configuration

All keyword lists and feeds are loaded from separate text files for easy editing:
  - tier1_keywords.txt  : Direct hit keywords (always relevant)
  - tier2_keywords.txt  : Context-dependent keywords (grouped by theme)
  - context_words.txt   : Words that make Tier 2 keywords relevant
  - feeds.txt           : RSS feed URLs
"""

import os

# =============================================================================
# FILE PATHS
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "kennisbank.db")
PDF_STORAGE_PATH = os.path.join(BASE_DIR, "pdfs")

# Keyword files
TIER1_KEYWORDS_FILE = os.path.join(BASE_DIR, "tier1_keywords.txt")
TIER2_KEYWORDS_FILE = os.path.join(BASE_DIR, "tier2_keywords.txt")
CONTEXT_WORDS_FILE = os.path.join(BASE_DIR, "context_words.txt")
FEEDS_FILE = os.path.join(BASE_DIR, "feeds.txt")

# =============================================================================
# FETCHER CONFIGURATION
# =============================================================================

REQUEST_TIMEOUT = 15
USER_AGENT = "ClimateMonitor/1.0 (Climate Adaptation Research Bot)"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _load_simple_list(filepath: str) -> list[str]:
    """Load a simple list of keywords from a file (one per line)."""
    keywords = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("["):
                    keywords.append(line.lower())
    except FileNotFoundError:
        print(f"Warning: File not found: {filepath}")
    return keywords


def load_tier1_keywords() -> list[str]:
    """Load Tier 1 (direct hit) keywords from file."""
    return _load_simple_list(TIER1_KEYWORDS_FILE)


def load_tier2_themes() -> dict[str, list[str]]:
    """
    Load Tier 2 keywords grouped by theme from file.
    
    Returns:
        Dict with theme names as keys and keyword lists as values
    """
    themes = {}
    current_theme = None
    
    try:
        with open(TIER2_KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                
                # Check for theme header [ThemeName]
                if line.startswith("[") and line.endswith("]"):
                    current_theme = line[1:-1]
                    themes[current_theme] = []
                elif current_theme:
                    themes[current_theme].append(line.lower())
                    
    except FileNotFoundError:
        print(f"Warning: Tier 2 keywords file not found: {TIER2_KEYWORDS_FILE}")
    
    return themes


def load_context_words() -> list[str]:
    """Load context words from file."""
    return _load_simple_list(CONTEXT_WORDS_FILE)


def get_tier2_keywords() -> list[str]:
    """Get all Tier 2 keywords as a flat list."""
    themes = load_tier2_themes()
    keywords = []
    for theme_keywords in themes.values():
        keywords.extend(theme_keywords)
    return keywords


def load_feeds() -> list[dict]:
    """
    Load RSS feeds from feeds.txt file.
    Format: URL | Source Name
    """
    feeds = []
    try:
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "|" in line:
                        url, source_name = line.split("|", 1)
                        feeds.append({
                            "url": url.strip(),
                            "source_name": source_name.strip()
                        })
                    else:
                        feeds.append({
                            "url": line,
                            "source_name": "Unknown"
                        })
    except FileNotFoundError:
        print(f"Warning: Feeds file not found: {FEEDS_FILE}")
    return feeds


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

# These are loaded once at import time for modules that expect them
TIER_2_THEMES = load_tier2_themes()
CONTEXT_WORDS = load_context_words()

def get_context_words() -> list[str]:
    """Get context words (for backward compatibility)."""
    return load_context_words()

def load_keywords() -> list[str]:
    """Load all keywords (Tier 1 + Tier 2) for backward compatibility."""
    return load_tier1_keywords() + get_tier2_keywords()

RELEVANCE_KEYWORDS = load_keywords()

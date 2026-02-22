"""
Climate Adaptation Knowledge Base - Configuration

All keyword lists and sources are loaded from separate text files for easy editing:
  - tier1_keywords.txt     : Direct hit keywords (always relevant, NL)
  - tier1_keywords_en.txt  : Optional direct hit keywords (EN)
  - tier2_keywords.txt     : Context-dependent keywords (grouped by theme)
  - context_words.txt      : Context words (NL)
  - context_words_en.txt   : Optional context words (EN)
  - sources.txt            : Multi-method source URLs (rss/sitemap/listing)
  - feeds.txt              : Legacy RSS-only source URLs
"""

import json
import os
from typing import TypedDict

# =============================================================================
# FILE PATHS
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("KA_DATA_DIR", BASE_DIR)
DATABASE_PATH = os.path.join(DATA_DIR, "kennisbank.db")
PDF_STORAGE_PATH = os.path.join(DATA_DIR, "pdfs")

# Keyword files
TIER1_KEYWORDS_FILE = os.path.join(BASE_DIR, "tier1_keywords.txt")
TIER1_KEYWORDS_EN_FILE = os.path.join(BASE_DIR, "tier1_keywords_en.txt")
TIER2_KEYWORDS_FILE = os.path.join(BASE_DIR, "tier2_keywords.txt")
CONTEXT_WORDS_FILE = os.path.join(BASE_DIR, "context_words.txt")
CONTEXT_WORDS_EN_FILE = os.path.join(BASE_DIR, "context_words_en.txt")

# Source files
FEEDS_FILE = os.path.join(BASE_DIR, "feeds.txt")
SOURCES_FILE = os.path.join(BASE_DIR, "sources.txt")
LISTING_SELECTORS_FILE = os.path.join(BASE_DIR, "listing_selectors.json")

PROMPTS_FILE = os.path.join(BASE_DIR, "prompts.json")

# =============================================================================
# FETCHER CONFIGURATION
# =============================================================================

REQUEST_TIMEOUT = 15
USER_AGENT = "ClimateMonitor/1.0 (Climate Adaptation Research Bot)"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


class SourceConfig(TypedDict):
    """Unified source configuration model."""

    method: str
    source_name: str
    url: str
    options: dict


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
        pass
    return keywords


def load_tier1_keywords() -> list[str]:
    """Load Tier 1 (direct hit) keywords from NL + optional EN files."""
    return _load_simple_list(TIER1_KEYWORDS_FILE) + _load_simple_list(TIER1_KEYWORDS_EN_FILE)


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

                if not line or line.startswith("#"):
                    continue

                if line.startswith("[") and line.endswith("]"):
                    current_theme = line[1:-1]
                    themes[current_theme] = []
                elif current_theme:
                    themes[current_theme].append(line.lower())

    except FileNotFoundError:
        print(f"Warning: Tier 2 keywords file not found: {TIER2_KEYWORDS_FILE}")

    return themes


def load_context_words() -> list[str]:
    """Load context words from NL + optional EN files."""
    return _load_simple_list(CONTEXT_WORDS_FILE) + _load_simple_list(CONTEXT_WORDS_EN_FILE)


def get_tier2_keywords() -> list[str]:
    """Get all Tier 2 keywords as a flat list."""
    themes = load_tier2_themes()
    keywords = []
    for theme_keywords in themes.values():
        keywords.extend(theme_keywords)
    return keywords


def load_feeds() -> list[dict]:
    """
    Load legacy RSS feeds from feeds.txt file.
    Format: URL | Source Name
    """
    feeds, _, _ = load_feeds_with_status()
    return feeds


def get_feeds_file_path() -> str:
    """Resolve feeds file path with priority: KA_FEEDS_FILE, /data/feeds.txt, repo feeds.txt."""
    env_feeds_file = os.getenv("KA_FEEDS_FILE")
    if env_feeds_file and os.path.exists(env_feeds_file):
        return env_feeds_file

    data_feeds_file = "/data/feeds.txt"
    if os.path.exists(data_feeds_file):
        return data_feeds_file

    return FEEDS_FILE


def load_feeds_with_status() -> tuple[list[dict], str | None, str]:
    """
    Load RSS feeds and return status details for UI/diagnostics.

    Returns:
        Tuple of (feeds, error_message, filepath_used)
    """
    feeds = []
    feeds_path = get_feeds_file_path()

    try:
        with open(feeds_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "|" in line:
                        url, source_name = line.split("|", 1)
                        feeds.append(
                            {
                                "url": url.strip(),
                                "source_name": source_name.strip(),
                            }
                        )
                    else:
                        feeds.append(
                            {
                                "url": line,
                                "source_name": "Unknown",
                            }
                        )
    except FileNotFoundError:
        return [], f"Feedsbestand niet gevonden: {feeds_path}", feeds_path
    except OSError as e:
        return [], f"Feedsbestand kan niet worden gelezen ({feeds_path}): {e}", feeds_path

    return feeds, None, feeds_path


def get_sources_file_path() -> str:
    """Resolve sources file path with priority: KA_SOURCES_FILE, /data/sources.txt, repo sources.txt."""
    env_sources_file = os.getenv("KA_SOURCES_FILE")
    if env_sources_file:
        return env_sources_file

    data_sources_file = "/data/sources.txt"
    if os.path.exists(data_sources_file):
        return data_sources_file

    return SOURCES_FILE


def _load_legacy_feeds_as_sources() -> tuple[list[SourceConfig], str | None, str]:
    """Fallback: map legacy feeds.txt entries to SourceConfig(method='rss')."""
    feeds, error, path = load_feeds_with_status()
    if error:
        return [], error, path

    return (
        [
            {
                "method": "rss",
                "source_name": feed["source_name"],
                "url": feed["url"],
                "options": {},
            }
            for feed in feeds
        ],
        None,
        path,
    )


def load_sources() -> list[SourceConfig]:
    """Load multi-method sources from sources.txt with fallback to feeds.txt."""
    sources, _, _ = load_sources_with_status()
    return sources


def load_sources_with_status() -> tuple[list[SourceConfig], str | None, str]:
    """
    Load sources and return status details for UI/diagnostics.

    File format:
      method | source_name | url | options_json
    """
    sources_path = get_sources_file_path()
    if not os.path.exists(sources_path):
        return _load_legacy_feeds_as_sources()

    sources: list[SourceConfig] = []
    try:
        with open(sources_path, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = [p.strip() for p in line.split("|", 3)]
                if len(parts) < 3:
                    return [], f"Ongeldige regel in sources bestand (regel {line_number}): {line}", sources_path

                method, source_name, url = parts[0].lower(), parts[1], parts[2]
                if method not in {"rss", "sitemap", "listing"}:
                    return [], f"Ongeldige methode '{method}' in regel {line_number}", sources_path

                options = {}
                if len(parts) == 4 and parts[3]:
                    try:
                        options = json.loads(parts[3])
                    except json.JSONDecodeError as e:
                        return [], f"JSON fout in sources regel {line_number}: {e}", sources_path

                sources.append(
                    {
                        "method": method,
                        "source_name": source_name,
                        "url": url,
                        "options": options if isinstance(options, dict) else {},
                    }
                )
    except OSError as e:
        return [], f"Sourcesbestand kan niet worden gelezen ({sources_path}): {e}", sources_path

    return sources, None, sources_path


def load_listing_selectors() -> dict:
    """Load listing selector definitions from listing_selectors.json."""
    try:
        with open(LISTING_SELECTORS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        print(f"Warning: Listing selectors file not found: {LISTING_SELECTORS_FILE}")
        return {}
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON in listing selectors file: {e}")
        return {}


def load_prompts() -> dict[str, str]:
    """
    Load AI prompts from prompts.json file.

    Returns:
        Dict with prompt names as keys and prompt templates as values
    """
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Prompts file not found: {PROMPTS_FILE}")
        return {
            "summary_prompt": "Maak een beknopte samenvatting van de volgende tekst...",
            "relevance_prompt": "Analyseer de relevantie voor de 21 opgaven...",
        }
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON in prompts file: {e}")
        return {}


def save_prompts(prompts: dict[str, str]) -> bool:
    """
    Save AI prompts to prompts.json file.

    Args:
        prompts: Dict with prompt names as keys and prompt templates as values

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving prompts: {e}")
        return False


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

TIER_2_THEMES = load_tier2_themes()
CONTEXT_WORDS = load_context_words()


def get_context_words() -> list[str]:
    """Get context words (for backward compatibility)."""
    return load_context_words()


def load_keywords() -> list[str]:
    """Load all keywords (Tier 1 + Tier 2) for backward compatibility."""
    return load_tier1_keywords() + get_tier2_keywords()


RELEVANCE_KEYWORDS = load_keywords()

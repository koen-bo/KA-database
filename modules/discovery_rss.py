"""
Discovery adapter for RSS sources.
"""

from datetime import datetime
import os
from typing import Optional, TypedDict
from urllib.parse import urlparse, urlunparse

import feedparser
import requests

from config import REQUEST_TIMEOUT, USER_AGENT, SourceConfig


class Candidate(TypedDict):
    title: str
    link: str
    summary: str
    publication_date: Optional[datetime]
    source_name: str
    discovery_method: str
    discovery_source_url: str


def _parse_date(entry) -> Optional[datetime]:
    """Parse publication date from RSS entry."""
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6])
            except Exception:
                continue
    return None


def discover_rss_candidates(source: SourceConfig) -> list[Candidate]:
    """
    Discover article candidates from an RSS feed source config.
    """
    # Fetch feed ourselves so we always apply configured headers/timeouts.
    headers_primary = {"User-Agent": USER_AGENT}
    headers_fallback = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    candidate_urls = [source["url"]]
    parsed = urlparse(source["url"])
    if parsed.netloc == "vng.nl":
        candidate_urls.append(
            urlunparse(parsed._replace(netloc="www.vng.nl"))
        )
    elif parsed.netloc == "www.vng.nl":
        candidate_urls.append(
            urlunparse(parsed._replace(netloc="vng.nl"))
        )

    response = None
    last_error = None
    for url in candidate_urls:
        for headers in (headers_primary, headers_fallback):
            try:
                candidate_response = requests.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if candidate_response.status_code >= 400:
                    last_error = RuntimeError(
                        f"HTTP {candidate_response.status_code} for {url}"
                    )
                    continue
                response = candidate_response
                break
            except requests.RequestException as e:
                last_error = e
                continue
        if response is not None:
            break

    if response is None:
        raise RuntimeError(f"Failed to fetch RSS feed: {last_error}")

    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Failed to parse RSS feed: {feed.bozo_exception}")

    default_cap = int(os.getenv("KA_MAX_ENTRIES_PER_FEED", "50"))
    global_cap = int(os.getenv("KA_MAX_CANDIDATES_PER_SOURCE", "60"))
    source_cap = int(source["options"].get("max_entries", default_cap))
    cap = min(default_cap, global_cap, source_cap)

    candidates: list[Candidate] = []
    for entry in feed.entries[:cap]:
        link = entry.get("link", "")
        if not link:
            continue
        candidates.append(
            {
                "title": entry.get("title", "No title"),
                "link": link,
                "summary": entry.get("summary", entry.get("description", "")),
                "publication_date": _parse_date(entry),
                "source_name": source["source_name"],
                "discovery_method": "rss",
                "discovery_source_url": source["url"],
            }
        )
    return candidates

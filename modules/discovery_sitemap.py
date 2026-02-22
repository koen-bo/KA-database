"""
Discovery adapter for sitemap sources.
"""

from datetime import datetime
import os
from typing import Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

from config import REQUEST_TIMEOUT, USER_AGENT, SourceConfig
from modules.discovery_rss import Candidate


def _normalize_text(value: Optional[str]) -> str:
    return value.strip() if isinstance(value, str) else ""


def _extract_title_from_url(link: str) -> str:
    path = urlparse(link).path.strip("/")
    if not path:
        return link
    slug = path.split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().title() or link


def _parse_lastmod(value: str) -> Optional[datetime]:
    value = _normalize_text(value)
    if not value:
        return None
    trimmed = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(trimmed)
    except ValueError:
        return None


def _is_before_threshold(value: Optional[datetime], threshold: Optional[datetime]) -> bool:
    """Safe datetime comparison across naive/aware values."""
    if value is None or threshold is None:
        return False
    if value.tzinfo and threshold.tzinfo is None:
        threshold = threshold.replace(tzinfo=value.tzinfo)
    elif threshold.tzinfo and value.tzinfo is None:
        value = value.replace(tzinfo=threshold.tzinfo)
    return value < threshold


def _is_allowed(link: str, include_prefixes: list[str], exclude_prefixes: list[str]) -> bool:
    if include_prefixes and not any(link.startswith(prefix) for prefix in include_prefixes):
        return False
    if exclude_prefixes and any(link.startswith(prefix) for prefix in exclude_prefixes):
        return False
    return True


def _download_xml(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text


def discover_sitemap_candidates(
    source: SourceConfig,
    min_publication_date: Optional[datetime] = None,
) -> list[Candidate]:
    """
    Discover candidates from a sitemap XML or sitemap index.
    """
    global_cap = int(os.getenv("KA_MAX_SITEMAP_URLS_PER_SOURCE", "120"))
    source_cap_raw = source["options"].get("max_urls")
    if source_cap_raw is not None:
        max_urls = int(source_cap_raw)
    else:
        max_urls = global_cap

    include_prefixes = source["options"].get("include_prefixes", [])
    exclude_prefixes = source["options"].get("exclude_prefixes", [])
    include_prefixes = include_prefixes if isinstance(include_prefixes, list) else []
    exclude_prefixes = exclude_prefixes if isinstance(exclude_prefixes, list) else []

    queue = [source["url"]]
    seen_sitemaps = set()
    seen_links = set()
    candidates: list[Candidate] = []
    scanned_urls = 0
    global_scan_cap = int(os.getenv("KA_MAX_SITEMAP_SCAN_URLS_PER_SOURCE", "800"))
    source_scan_cap = int(source["options"].get("max_scan_urls", global_scan_cap))
    max_scan_urls = max(1, source_scan_cap)

    skipped_sitemaps = 0

    while queue and len(candidates) < max_urls and scanned_urls < max_scan_urls:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            xml_content = _download_xml(sitemap_url)
            root = ET.fromstring(xml_content)
        except Exception as e:
            skipped_sitemaps += 1
            print(f"    [SITEMAP WARNING] Skipping sitemap {sitemap_url}: {e}")
            continue

        tag = root.tag.lower()

        # Handle sitemap index
        if tag.endswith("sitemapindex"):
            for node in root.findall(".//{*}sitemap/{*}loc"):
                child_sitemap = _normalize_text(node.text)
                if child_sitemap and child_sitemap not in seen_sitemaps:
                    queue.append(child_sitemap)
            continue

        # Handle urlset
        for url_node in root.findall(".//{*}url"):
            scanned_urls += 1
            if scanned_urls > max_scan_urls:
                break
            loc = _normalize_text(url_node.findtext("{*}loc"))
            if not loc or loc in seen_links:
                continue
            if not _is_allowed(loc, include_prefixes, exclude_prefixes):
                continue

            lastmod = _parse_lastmod(url_node.findtext("{*}lastmod"))
            if _is_before_threshold(lastmod, min_publication_date):
                continue

            seen_links.add(loc)
            candidates.append(
                {
                    "title": _extract_title_from_url(loc),
                    "link": loc,
                    "summary": "",
                    "publication_date": lastmod,
                    "source_name": source["source_name"],
                    "discovery_method": "sitemap",
                    "discovery_source_url": source["url"],
                }
            )
            if len(candidates) >= max_urls:
                break

    if skipped_sitemaps:
        print(f"    [SITEMAP INFO] Skipped {skipped_sitemaps} unreadable sitemap file(s).")

    return candidates

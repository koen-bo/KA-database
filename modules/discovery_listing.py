"""
Discovery adapter for HTML listing sources.
"""

from datetime import datetime
import os
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config
from config import REQUEST_TIMEOUT, USER_AGENT, SourceConfig
from modules.discovery_rss import Candidate


def _first_text(node, selector: str) -> str:
    if not selector:
        return ""
    target = node.select_one(selector)
    return target.get_text(" ", strip=True) if target else ""


def _parse_date(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
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


def _extract_candidates_from_page(
    html_text: str,
    base_url: str,
    source_name: str,
    discovery_source_url: str,
    selector_cfg: dict,
) -> list[Candidate]:
    soup = BeautifulSoup(html_text, "html.parser")
    item_selector = selector_cfg.get("item_selector", "article")
    link_selector = selector_cfg.get("link_selector", "a")
    title_selector = selector_cfg.get("title_selector", "")
    date_selector = selector_cfg.get("date_selector", "")
    summary_selector = selector_cfg.get("summary_selector", "")

    items = soup.select(item_selector)
    candidates: list[Candidate] = []
    seen_links = set()

    for item in items:
        link_node = item.select_one(link_selector)
        href = (link_node.get("href", "").strip() if link_node else "")
        if not href:
            continue
        link = urljoin(base_url, href)
        if link in seen_links:
            continue
        seen_links.add(link)

        title = _first_text(item, title_selector) if title_selector else ""
        if not title and link_node:
            title = link_node.get_text(" ", strip=True)
        if not title:
            title = link

        summary = _first_text(item, summary_selector)
        date_text = _first_text(item, date_selector)

        candidates.append(
            {
                "title": title,
                "link": link,
                "summary": summary,
                "publication_date": _parse_date(date_text),
                "source_name": source_name,
                "discovery_method": "listing",
                "discovery_source_url": discovery_source_url,
            }
        )

    return candidates


def discover_listing_candidates(
    source: SourceConfig,
    min_publication_date: Optional[datetime] = None,
) -> list[Candidate]:
    """
    Discover candidates from a paginated listing page using selector config.
    """
    selectors = config.load_listing_selectors()
    selector_key = source["options"].get("selector_key", "")
    selector_cfg = selectors.get(selector_key)
    if not isinstance(selector_cfg, dict):
        raise RuntimeError(f"Missing listing selector config for key: {selector_key}")

    global_cap = int(os.getenv("KA_MAX_CANDIDATES_PER_SOURCE", "60"))
    source_cap = int(source["options"].get("max_candidates", global_cap))
    max_candidates = min(global_cap, source_cap)

    global_pages = int(os.getenv("KA_MAX_LISTING_PAGES_PER_SOURCE", "2"))
    source_pages = int(source["options"].get("max_pages", global_pages))
    max_pages = min(global_pages, source_pages)

    pagination_selector = selector_cfg.get("pagination_selector", "")
    next_page_selector = selector_cfg.get("next_page_selector", "a[rel='next']")

    candidates: list[Candidate] = []
    visited_pages = set()
    current_url = source["url"]

    for _ in range(max_pages):
        if not current_url or current_url in visited_pages:
            break
        visited_pages.add(current_url)

        response = requests.get(
            current_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        page_candidates = _extract_candidates_from_page(
            html_text=response.text,
            base_url=current_url,
            source_name=source["source_name"],
            discovery_source_url=source["url"],
            selector_cfg=selector_cfg,
        )
        for candidate in page_candidates:
            if _is_before_threshold(candidate.get("publication_date"), min_publication_date):
                continue
            candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break

        if not pagination_selector:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        pagination_scope = soup.select_one(pagination_selector) if pagination_selector else soup
        next_node = pagination_scope.select_one(next_page_selector) if pagination_scope else None
        next_href = (next_node.get("href", "").strip() if next_node else "")
        current_url = urljoin(current_url, next_href) if next_href else ""

    # De-duplicate and cap while preserving order
    deduped: list[Candidate] = []
    seen_links = set()
    for item in candidates:
        if item["link"] in seen_links:
            continue
        seen_links.add(item["link"])
        deduped.append(item)
        if len(deduped) >= max_candidates:
            break
    return deduped

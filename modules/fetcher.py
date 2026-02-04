"""
Climate Adaptation Knowledge Base - Content Fetcher

Handles downloading and extracting text from HTML pages and PDF documents.
PDFs are saved locally for easy preview/access.
"""

import io
import os
import re
from datetime import datetime
from typing import Optional, TypedDict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

import config


class FetchResult(TypedDict):
    """Return type for content fetching operations."""
    text: str
    type: str  # 'pdf' or 'html'
    file_path: Optional[str]  # Local path for PDFs, None for HTML


class ContentFetcher:
    """
    Fetches and extracts text content from URLs.
    
    Handles both HTML pages and PDF documents. PDF files are saved
    locally to the configured PDF storage folder.
    """
    
    def __init__(self):
        """Initialize the fetcher with configured settings."""
        self.timeout = config.REQUEST_TIMEOUT
        self.user_agent = config.USER_AGENT
        self.pdf_folder = config.PDF_STORAGE_PATH
        
        # Ensure PDF folder exists
        os.makedirs(self.pdf_folder, exist_ok=True)
    
    def fetch(self, url: str, source_name: str = "unknown", title: str = "") -> Optional[FetchResult]:
        """
        Fetch content from a URL and extract text.
        
        Args:
            url: The URL to fetch
            source_name: Source name for PDF filename
            title: Document title for PDF filename
        
        Returns:
            FetchResult dict with text, type, and file_path, or None on error
        """
        try:
            # Make HTTP request
            headers = {"User-Agent": self.user_agent}
            response = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
            
            # Detect content type
            content_type = response.headers.get("Content-Type", "").lower()
            
            # Check if PDF
            if self._is_pdf(url, content_type):
                return self._process_pdf(response.content, url, source_name, title)
            else:
                # Process HTML, but also check for embedded PDF links
                return self._process_html_with_pdf_check(response.text, url, source_name, title)
                
        except requests.exceptions.Timeout:
            print(f"[Fetcher] Timeout fetching {url}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[Fetcher] Error fetching {url}: {e}")
            return None
        except Exception as e:
            print(f"[Fetcher] Unexpected error processing {url}: {e}")
            return None
    
    def _is_pdf(self, url: str, content_type: str) -> bool:
        """Detect if the content is a PDF based on headers or URL."""
        # Check Content-Type header
        if "application/pdf" in content_type:
            return True
        
        # Check URL extension
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(".pdf"):
            return True
        
        return False
    
    def _process_pdf(
        self, 
        content: bytes, 
        url: str, 
        source_name: str, 
        title: str
    ) -> Optional[FetchResult]:
        """
        Process PDF content: save to disk and extract text.
        
        Args:
            content: Raw PDF bytes
            url: Original URL (for fallback naming)
            source_name: Source name for filename
            title: Document title for filename
        
        Returns:
            FetchResult with extracted text and local file path
        """
        try:
            # Generate filename
            filename = self._generate_pdf_filename(source_name, title, url)
            file_path = os.path.join(self.pdf_folder, filename)
            
            # Save PDF to disk
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Extract text using pypdf
            pdf_file = io.BytesIO(content)
            reader = PdfReader(pdf_file)
            
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            full_text = "\n\n".join(text_parts)
            
            if not full_text.strip():
                print(f"[Fetcher] Warning: No text extracted from PDF {url}")
            
            return {
                "text": full_text,
                "type": "pdf",
                "file_path": file_path
            }
            
        except Exception as e:
            print(f"[Fetcher] Error processing PDF: {e}")
            return None
    
    def _process_html_with_pdf_check(
        self, 
        html_content: str, 
        url: str, 
        source_name: str, 
        title: str
    ) -> Optional[FetchResult]:
        """
        Process HTML content, checking for embedded PDF download links.
        
        For government document pages (rijksoverheid.nl, etc.), the actual PDF
        is often linked via open.overheid.nl. This method extracts that PDF.
        
        Uses smart detection to avoid downloading supplementary PDFs from
        sidebars or "related publications" sections.
        
        Args:
            html_content: Raw HTML string
            url: Original page URL
            source_name: Source name for PDF filename
            title: Document title for PDF filename (used for matching)
        
        Returns:
            FetchResult with extracted text and optional PDF file_path
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Check for PDF download links (common on government document pages)
            # Pass article title for smart matching
            pdf_url = self._find_pdf_download_link(soup, url, article_title=title)
            
            if pdf_url:
                # Try to download the PDF
                pdf_result = self._download_pdf_from_url(pdf_url, source_name, title)
                if pdf_result:
                    return pdf_result
            
            # Fall back to regular HTML processing
            return self._process_html(html_content)
            
        except Exception as e:
            print(f"[Fetcher] Error processing HTML with PDF check: {e}")
            return self._process_html(html_content)
    
    def _find_pdf_download_link(self, soup: BeautifulSoup, page_url: str, article_title: str = "") -> Optional[str]:
        """
        Find PDF download links in HTML page with smart context detection.
        
        Uses multiple detection strategies with context-aware penalties:
        1. Direct .pdf links in href (boosted)
        2. open.overheid.nl document links (boosted)
        3. Links with "download" in text and PDF-related content
        4. PENALTIES for PDFs in sidebars, footers, "related" sections
        5. Title matching: boost if PDF filename matches article title
        
        Args:
            soup: BeautifulSoup parsed HTML
            page_url: Original page URL for context
            article_title: Article title for matching against PDF filename
        
        Returns:
            PDF URL if found and score >= threshold, None otherwise
        """
        MIN_SCORE_THRESHOLD = 120  # Minimum score to accept a PDF (high to avoid supplementary docs)
        
        parsed_page = urlparse(page_url)
        base_url = f"{parsed_page.scheme}://{parsed_page.netloc}"
        
        # Collect all potential PDF links with priority scores
        pdf_candidates = []
        
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            text = link.get_text(strip=True).lower()
            
            if not href:
                continue
            
            score = 0
            penalties = []
            
            # Check href patterns
            href_lower = href.lower()
            
            # Direct .pdf extension (highest priority)
            if href_lower.endswith(".pdf"):
                score += 100
            
            # open.overheid.nl document links
            if "open.overheid.nl" in href_lower and "/file" in href_lower:
                score += 90
            
            # officielebekendmakingen.nl
            if "officielebekendmakingen.nl" in href_lower:
                score += 80
            
            # .pdf anywhere in URL
            if ".pdf" in href_lower:
                score += 70
            
            # =================================================================
            # PAGE CONTEXT BOOST - Document pages should fetch PDFs
            # =================================================================
            page_url_lower = page_url.lower()
            # Rijksoverheid document pages (kamerstukken, rapporten, etc.)
            if any(doc_type in page_url_lower for doc_type in 
                   ["/kamerstukken/", "/rapporten/", "/publicaties/", "/documenten/", 
                    "/beleidsnotas/", "/brieven/", "/besluiten/"]):
                score += 50
                penalties.append("doc_page_boost:+50")
            
            # Check link text patterns
            if "download" in text and ("pdf" in text or "rapport" in text or "advies" in text):
                score += 50
            
            if "(pdf" in text:
                score += 40
            
            if "volledige" in text and ("advies" in text or "rapport" in text):
                score += 30
            
            # Skip if no relevant patterns found
            if score == 0:
                continue
            
            # =================================================================
            # CONTEXT PENALTIES - Check if link is in supplementary sections
            # =================================================================
            context_penalty = self._get_link_context_penalty(link)
            if context_penalty > 0:
                penalties.append(f"context:-{context_penalty}")
            score -= context_penalty
            
            # Check link text for supplementary indicators
            supplementary_texts = ["gerelateerd", "meer lezen", "achtergrond", "bijlage", 
                                   "zie ook", "lees ook", "related", "background",
                                   "publicatie", "bron:", "bron "]
            for supp_text in supplementary_texts:
                if supp_text in text:
                    score -= 40
                    penalties.append(f"text:{supp_text}:-40")
                    break
            
            # Extra penalty if link text mentions a different topic/report name
            # (e.g., "PBL-rapport" when article is about "Wetgevingsoverleg")
            if "rapport" in text or "advies" in text or "publicatie" in text:
                # This might be a reference to another document
                score -= 20
                penalties.append("ref_to_other_doc:-20")
            
            # =================================================================
            # TITLE MATCHING - Boost if PDF filename OR link text matches article title
            # =================================================================
            if article_title:
                # Check both URL and link text for title match
                url_match = self._get_title_match_score(article_title, href)
                text_match = self._get_title_match_score(article_title, text) if text else 0
                
                # Use the better of the two scores
                title_match_score = max(url_match, text_match)
                
                if title_match_score != 0:
                    if title_match_score > 0:
                        penalties.append(f"title_match:+{title_match_score}")
                    else:
                        penalties.append(f"title_mismatch:{title_match_score}")
                score += title_match_score
            
            # Make absolute URL
            if href.startswith("/"):
                href = base_url + href
            elif not href.startswith("http"):
                # Relative path
                continue
            
            penalty_str = ", ".join(penalties) if penalties else "none"
            pdf_candidates.append((score, href, text[:50], penalty_str))
        
        # Sort by score (highest first)
        if pdf_candidates:
            pdf_candidates.sort(key=lambda x: x[0], reverse=True)
            best_match = pdf_candidates[0]
            
            # Check minimum threshold
            if best_match[0] >= MIN_SCORE_THRESHOLD:
                print(f"[Fetcher] Found PDF link (score {best_match[0]}, adjustments: {best_match[3]}): {best_match[2]}")
                return best_match[1]
            else:
                print(f"[Fetcher] PDF rejected (score {best_match[0]} < {MIN_SCORE_THRESHOLD}, adjustments: {best_match[3]}): {best_match[2]}")
                return None
        
        return None
    
    def _get_link_context_penalty(self, link) -> int:
        """
        Calculate penalty based on where the link appears on the page.
        
        Links in sidebars, footers, and "related content" sections are
        likely supplementary material, not the main document.
        
        Args:
            link: BeautifulSoup link element
        
        Returns:
            Penalty score (0 = no penalty, higher = more suspicious)
        """
        penalty = 0
        
        # Check parent elements for context clues
        for parent in link.parents:
            if parent.name is None:
                continue
            
            # Check tag names
            if parent.name in ["aside", "footer", "nav"]:
                penalty += 50
                break
            
            # Check class names
            parent_classes = " ".join(parent.get("class", [])).lower()
            
            suspicious_classes = [
                "related", "sidebar", "footer", "widget", "aside",
                "publicaties", "gerelateerd", "more", "extra", 
                "recommended", "also", "links", "nav"
            ]
            
            for susp in suspicious_classes:
                if susp in parent_classes:
                    penalty += 40
                    break
            
            # Check id
            parent_id = (parent.get("id") or "").lower()
            for susp in suspicious_classes:
                if susp in parent_id:
                    penalty += 40
                    break
            
            if penalty > 0:
                break
        
        return min(penalty, 60)  # Cap penalty at 60
    
    def _get_title_match_score(self, article_title: str, pdf_url: str) -> int:
        """
        Calculate score adjustment based on title matching.
        
        If the PDF filename contains keywords from the article title,
        it's more likely to be the main document.
        
        Args:
            article_title: Article/document title
            pdf_url: URL to the PDF
        
        Returns:
            Score adjustment (+30 for match, -20 for clear mismatch, 0 for uncertain)
        """
        if not article_title:
            return 0
        
        # Extract filename from URL
        parsed = urlparse(pdf_url)
        filename = parsed.path.split("/")[-1].lower()
        
        # Clean up filename (remove extension, replace separators)
        filename_clean = re.sub(r"\.pdf$", "", filename)
        filename_clean = re.sub(r"[-_]", " ", filename_clean)
        
        # Extract keywords from article title (words > 3 chars)
        title_words = re.findall(r"\b\w{4,}\b", article_title.lower())
        # Remove common Dutch stop words
        stop_words = {"deze", "voor", "over", "naar", "door", "zijn", "wordt", "worden", 
                      "hebben", "heeft", "ging", "hier", "daar", "toen", "maar", "meer"}
        title_words = [w for w in title_words if w not in stop_words]
        
        if not title_words:
            return 0
        
        # Count matches
        matches = sum(1 for word in title_words if word in filename_clean)
        match_ratio = matches / len(title_words)
        
        if match_ratio >= 0.4:  # 40%+ words match
            return 40
        elif match_ratio >= 0.2:  # Some match
            return 20
        elif matches == 0 and len(title_words) >= 3:
            # Clear mismatch: no keywords match and title has enough words
            return -50  # Strong penalty for mismatched titles
        
        return 0
    
    def _download_pdf_from_url(
        self, 
        pdf_url: str, 
        source_name: str, 
        title: str
    ) -> Optional[FetchResult]:
        """
        Download a PDF from a URL and process it.
        
        Args:
            pdf_url: URL to the PDF file
            source_name: Source name for filename
            title: Document title for filename
        
        Returns:
            FetchResult with PDF text and file_path, or None on error
        """
        try:
            print(f"[Fetcher] Downloading PDF: {pdf_url[:60]}...")
            headers = {"User-Agent": self.user_agent}
            response = requests.get(pdf_url, headers=headers, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
            
            content_type = response.headers.get("Content-Type", "").lower()
            
            # Verify it's actually a PDF
            if "application/pdf" in content_type or response.content[:4] == b"%PDF":
                return self._process_pdf(response.content, pdf_url, source_name, title)
            else:
                print(f"[Fetcher] URL did not return PDF: {content_type}")
                return None
                
        except Exception as e:
            print(f"[Fetcher] Error downloading PDF: {e}")
            return None
    
    def _process_html(self, html_content: str) -> Optional[FetchResult]:
        """
        Process HTML content: remove clutter and extract main text.
        
        Args:
            html_content: Raw HTML string
        
        Returns:
            FetchResult with extracted text (file_path is None for HTML)
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Remove clutter elements
            for tag in soup.find_all(["script", "style", "nav", "footer", "aside", "header", "noscript"]):
                tag.decompose()
            
            # Try to find main content areas first
            main_content = None
            for selector in ["main", "article", "[role='main']", ".content", "#content"]:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            # Use main content if found, otherwise use body
            if main_content:
                text = main_content.get_text(separator="\n", strip=True)
            else:
                body = soup.find("body")
                if body:
                    text = body.get_text(separator="\n", strip=True)
                else:
                    text = soup.get_text(separator="\n", strip=True)
            
            # Clean up excessive whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r" {2,}", " ", text)
            
            return {
                "text": text.strip(),
                "type": "html",
                "file_path": None
            }
            
        except Exception as e:
            print(f"[Fetcher] Error processing HTML: {e}")
            return None
    
    def _generate_pdf_filename(self, source_name: str, title: str, url: str) -> str:
        """
        Generate a unique, filesystem-safe filename for a PDF.
        
        Format: {source}_{timestamp}_{sanitized_title}.pdf
        
        Args:
            source_name: Source name (e.g., "Tweede Kamer")
            title: Document title
            url: Original URL (fallback for naming)
        
        Returns:
            Safe filename string
        """
        # Sanitize source name
        safe_source = self._sanitize_filename(source_name) or "unknown"
        
        # Sanitize title (truncate if too long)
        safe_title = self._sanitize_filename(title)
        if not safe_title:
            # Use URL path as fallback
            parsed = urlparse(url)
            safe_title = self._sanitize_filename(parsed.path.split("/")[-1]) or "document"
        safe_title = safe_title[:50]  # Limit length
        
        # Add timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        return f"{safe_source}_{timestamp}_{safe_title}.pdf"
    
    def _sanitize_filename(self, text: str) -> str:
        """
        Remove or replace characters that are invalid in filenames.
        
        Args:
            text: Original text
        
        Returns:
            Filesystem-safe string
        """
        if not text:
            return ""
        
        # Replace spaces and common separators with underscores
        text = re.sub(r"[\s\-]+", "_", text)
        
        # Remove invalid filename characters
        text = re.sub(r'[<>:"/\\|?*]', "", text)
        
        # Remove any non-ASCII characters for maximum compatibility
        text = text.encode("ascii", "ignore").decode("ascii")
        
        # Remove leading/trailing underscores and dots
        text = text.strip("_.")
        
        return text

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
                return self._process_html(response.text)
                
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

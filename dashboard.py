"""
Climate Adaptation Knowledge Base - Dashboard

A Streamlit frontend to:
- Search and browse documents (list/card views)
- Edit zoektermen and AI prompts
- Access PDF files
- Run the ingestion pipeline
- Human-in-the-loop AI workflow

Run with: streamlit run dashboard.py
"""

import json
import hmac
import html
import os
import re
import subprocess
import textwrap
import hashlib
from base64 import b64encode
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from sqlalchemy import or_, func

from modules.database import get_session, Document, init_db
from modules.fetcher import ContentFetcher
from modules.screening import (
    build_llm_screening_request,
    build_screening_input,
    build_screening_user_message,
    compile_screening_system_prompt,
    count_words,
    screening_output_schema,
    serialize_llm_screening_request,
)
from modules.source_metadata import (
    PARLIAMENT_DOC_TYPES,
    RIJKSOVERHEID_DOC_TYPES,
    get_parliament_source_names,
    get_rijksoverheid_source_names,
)
import config

# Page config
st.set_page_config(
    page_title="Klimaatadaptatie KB",
    page_icon="KB",
    layout="wide"
)

# Initialize database
init_db()

# Custom CSS for cards
st.markdown("""
<style>
.card-shell {
    border: 1px solid #e8edf3;
    border-radius: 14px;
    background: #ffffff;
    overflow: hidden;
    box-shadow: 0 2px 10px rgba(12, 24, 36, 0.06);
    transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
    margin-bottom: 0;
    width: 100%;
    max-width: none;
    display: flex;
    flex-direction: column;
    min-height: 100%;
}
.card-shell:hover {
    transform: translateY(-2px);
    border-color: #c4d4e6;
    box-shadow: 0 8px 20px rgba(12, 24, 36, 0.12);
}
.card-thumb {
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
    display: block;
}
.card-content {
    padding: 12px 14px 6px 14px;
    flex: 1 1 auto;
}
.card-tags {
    margin-bottom: 8px;
    min-height: 24px;
}
.card-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    margin-right: 6px;
    margin-bottom: 6px;
    background: #e8f2ff;
    color: #14508d;
}
.card-tag-overflow {
    background: #eef2f6;
    color: #3b4c61;
}
.card-meta {
    color: #73859a;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 8px;
}
.card-title {
    color: #1b2b3a;
    font-size: 18px;
    line-height: 1.28;
    font-weight: 750;
    margin-bottom: 8px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 70px;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.card-summary {
    color: #687b90;
    font-size: 14px;
    line-height: 1.45;
    margin-bottom: 10px;
    display: -webkit-box;
    -webkit-line-clamp: 8;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 140px;
}
.card-cta-wrap {
    padding: 0 14px 14px 14px;
}
.card-cta {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #3d82d8;
    font-weight: 600;
    font-size: 16px;
    text-decoration: none;
}
.card-cta:hover {
    color: #2f72c6;
}
.card-cta-icon {
    width: 18px;
    height: 18px;
    border: 1px solid #8cb4e5;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    line-height: 1;
}
.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 300px));
    gap: 14px;
    align-items: stretch;
    justify-content: start;
}
@media (max-width: 640px) {
    .card-grid {
        grid-template-columns: minmax(220px, 1fr);
        gap: 10px;
    }
}
.detail-hero {
    border: 1px solid #e7edf3;
    border-radius: 18px;
    background: linear-gradient(180deg, #fbfdff 0%, #f4f8fb 100%);
    padding: 20px 22px;
    margin-bottom: 16px;
}
.detail-meta-row {
    color: #607489;
    font-size: 14px;
    line-height: 1.5;
    margin-top: 6px;
}
.detail-url {
    color: #2f72c6;
    text-decoration: none;
    word-break: break-word;
}
.detail-summary-card {
    border: 1px solid #e7edf3;
    border-radius: 18px;
    background: #ffffff;
    padding: 18px 20px;
    margin-bottom: 16px;
    box-shadow: 0 2px 10px rgba(12, 24, 36, 0.04);
}
.detail-section-card {
    border: 1px solid #e7edf3;
    border-radius: 18px;
    background: #ffffff;
    padding: 18px 20px;
    margin-bottom: 16px;
    box-shadow: 0 2px 10px rgba(12, 24, 36, 0.04);
}
.detail-thumb {
    width: 100%;
    max-width: 280px;
    aspect-ratio: 16 / 10;
    object-fit: cover;
    border-radius: 16px;
    border: 1px solid #d9e3ee;
    display: block;
    margin-left: auto;
}
.score-badge {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 10px;
}
.score-high {
    background: #e8f7ef;
    color: #1c6b43;
}
.score-medium {
    background: #fff4df;
    color: #9a6500;
}
.score-low {
    background: #fbeaea;
    color: #9a2f2f;
}
.tag-pill {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    background: #eef5fb;
    color: #244864;
    font-size: 13px;
    font-weight: 600;
    margin-right: 8px;
    margin-bottom: 8px;
}
.tag-pill-muted {
    background: #f3f5f7;
    color: #56687a;
}
.detail-kicker {
    color: #6b7f93;
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 8px;
}
.detail-note {
    color: #64788d;
    font-size: 14px;
    margin-top: 6px;
}
</style>
""", unsafe_allow_html=True)


def get_auth_config() -> tuple[str | None, str | None]:
    """Load dashboard login credentials from environment variables."""
    username = os.getenv("KA_DASHBOARD_USERNAME")
    password = os.getenv("KA_DASHBOARD_PASSWORD")
    return username, password


def auth_config_valid() -> bool:
    """Return True when both required auth environment variables are set."""
    username, password = get_auth_config()
    return bool(username and password)


def check_credentials(input_username: str, input_password: str) -> bool:
    """Compare provided credentials against configured values."""
    configured_username, configured_password = get_auth_config()
    if not configured_username or not configured_password:
        return False
    return (
        hmac.compare_digest(input_username, configured_username)
        and hmac.compare_digest(input_password, configured_password)
    )


def ensure_auth_state_initialized() -> None:
    """Initialize auth-related session state fields."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "auth_username" not in st.session_state:
        st.session_state.auth_username = ""
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = ""


def _get_auth_signing_secret() -> str:
    """Return secret material for signing lightweight auth tokens."""
    username, password = get_auth_config()
    return f"{username or ''}:{password or ''}"


def build_auth_token(username: str, expires_at: datetime | None = None) -> str:
    """Build a signed auth token suitable for query-param persistence."""
    if not expires_at:
        expires_at = datetime.utcnow() + timedelta(days=30)
    expiry = expires_at.strftime("%Y%m%d%H%M%S")
    payload = f"{username}|{expiry}"
    signature = hmac.new(
        _get_auth_signing_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{expiry}.{signature[:24]}"


def validate_auth_token(token: str | None) -> str | None:
    """Validate a signed auth token and return the username when valid."""
    if not token:
        return None
    try:
        expiry, signature = str(token).split(".", 1)
    except ValueError:
        return None
    configured_username, _ = get_auth_config()
    username = configured_username or ""
    payload = f"{username}|{expiry}"
    expected = hmac.new(
        _get_auth_signing_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        expires_at = datetime.strptime(expiry, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if datetime.utcnow() > expires_at:
        return None
    if configured_username and username != configured_username:
        return None
    return username


def restore_auth_from_query_params() -> None:
    """Restore auth state from signed query param when present."""
    if st.session_state.get("authenticated"):
        return
    token = st.query_params.get("a")
    username = validate_auth_token(token)
    if username:
        st.session_state.authenticated = True
        st.session_state.auth_username = username
        st.session_state.auth_token = str(token)
    elif token:
        try:
            del st.query_params["a"]
        except Exception:
            pass


def render_login_screen() -> None:
    """Render the login form and authenticate the user."""
    st.title("Inloggen")
    st.write("Voer je gebruikersnaam en wachtwoord in om toegang te krijgen.")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Gebruikersnaam")
        password = st.text_input("Wachtwoord", type="password")
        submitted = st.form_submit_button("Inloggen", type="primary")

    if submitted:
        if check_credentials(username, password):
            st.session_state.authenticated = True
            st.session_state.auth_username = username
            token = build_auth_token(username)
            st.session_state.auth_token = token
            st.query_params["a"] = token
            st.rerun()
        else:
            st.error("Onjuiste gebruikersnaam of wachtwoord.")


def render_logout_control() -> None:
    """Render logout control in sidebar for authenticated users."""
    if st.sidebar.button("Uitloggen"):
        st.session_state.authenticated = False
        st.session_state.auth_username = ""
        st.session_state.auth_token = ""
        for key in ("a", "open_doc"):
            try:
                del st.query_params[key]
            except Exception:
                pass
        st.rerun()


def get_unique_sources() -> list[str]:
    """Get unique source names from database."""
    with get_session() as session:
        sources = session.query(Document.source_name).distinct().all()
        return sorted([s[0] for s in sources if s[0]])


def get_unique_doc_types() -> list[str]:
    """Get distinct doc_type values currently present in the database."""
    with get_session() as session:
        doc_types = session.query(Document.doc_type).distinct().all()
        present = {d[0] for d in doc_types if d[0]}
        ordered = [doc_type for doc_type in RIJKSOVERHEID_DOC_TYPES if doc_type in present]
        extras = sorted(present.difference(ordered))
        return ordered + extras


@st.cache_data(ttl=300)
def get_rijksoverheid_source_groups() -> tuple[list[str], list[str]]:
    """Return configured Rijksoverheid and parliament-oriented source names."""
    sources = config.load_sources()
    return get_rijksoverheid_source_names(sources), get_parliament_source_names(sources)


def parse_keyword_tags(raw: str | None) -> list[str]:
    """Parse keyword tag JSON into a normalized list."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    tags: list[str] = []
    for item in data:
        if isinstance(item, str):
            cleaned = item.strip().lower()
            if cleaned:
                tags.append(cleaned)
    return sorted(set(tags))


@st.cache_data(ttl=300)
def get_tier1_keyword_set() -> set[str]:
    """Load Tier 1 keywords as lowercase set for tag display filtering."""
    return {kw.strip().lower() for kw in config.load_tier1_keywords() if kw and kw.strip()}


def get_tier1_tag_chips(doc_tags: list[str]) -> tuple[list[str], int]:
    """Return up to 3 tier1 tags and overflow count for card chips."""
    tier1_set = get_tier1_keyword_set()
    tier1_tags = sorted([tag for tag in doc_tags if tag in tier1_set])
    visible = tier1_tags[:3]
    overflow = max(0, len(tier1_tags) - len(visible))
    return visible, overflow


def extract_html_text_for_summary(full_text: str | None) -> str:
    """Use only HTML text for summary when PDF extract is appended."""
    if not full_text:
        return ""
    text = str(full_text)
    delimiter = "[PDF EXTRACT]"
    if delimiter in text:
        text = text.split(delimiter, 1)[0]
    return re.sub(r"\s+", " ", text).strip()


def _strip_summary_leading_noise(text: str, source_name: str = "", publication_date: datetime | None = None) -> str:
    """Trim common leading noise like dates, source names, and byline fragments."""
    cleaned = text.strip()
    patterns = [
        r"^\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*[|/,\-]?\s*",
        r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*[|/,\-]?\s*",
        r"^\s*(door|by)\s+[^.!?]{2,70}\s*[|/,\-]?\s*",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    if source_name:
        source_pattern = re.escape(source_name.strip())
        cleaned = re.sub(rf"^\s*{source_pattern}\s*[|/,\-]?\s*", "", cleaned, flags=re.IGNORECASE).strip()

    if publication_date:
        for date_pattern in (
            publication_date.strftime("%d-%m-%Y"),
            publication_date.strftime("%Y-%m-%d"),
            publication_date.strftime("%d/%m/%Y"),
        ):
            if date_pattern:
                cleaned = re.sub(rf"^\s*{re.escape(date_pattern)}\s*[|/,\-]?\s*", "", cleaned).strip()
    return cleaned


def build_card_summary(full_text: str | None, source_name: str = "", publication_date: datetime | None = None) -> str:
    """Create short card summary from extracted HTML text."""
    base_text = extract_html_text_for_summary(full_text)
    if not base_text:
        return "Geen samenvatting beschikbaar."

    cleaned = _strip_summary_leading_noise(base_text, source_name=source_name, publication_date=publication_date)
    if not cleaned:
        return "Geen samenvatting beschikbaar."

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    picked = [s.strip() for s in sentences if s and len(s.strip()) > 8][:2]
    if picked:
        summary = " ".join(picked)
    else:
        summary = cleaned[:220]
        if len(cleaned) > 220:
            summary += "..."
    return summary


def parse_screening_output(raw: str | None) -> dict | None:
    """Parse stored screening JSON safely for detail rendering."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def format_detail_date(value: datetime | None) -> str:
    """Format a date or datetime for detail screens."""
    if not value:
        return "Onbekend"
    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        return "Onbekend"


def get_score_badge_class(score: int | None) -> str:
    """Return CSS class for relevance score badge."""
    if score is None:
        return "score-medium"
    if score >= 8:
        return "score-high"
    if score >= 5:
        return "score-medium"
    return "score-low"


def get_score_interpretation(score: int | None) -> str:
    """Return short interpretation line for the RVO relevance score."""
    if score is None:
        return "Nog geen screeningsscore beschikbaar."
    if score >= 9:
        return "Zeer relevant voor RVO's klimaatadaptatie-opgave."
    if score >= 7:
        return "Duidelijk relevant voor RVO, maar niet de meest directe uitvoeringsrol."
    if score >= 4:
        return "Inhoudelijk relevant, maar vaak meer voor andere publieke partijen dan voor RVO."
    if score >= 1:
        return "Slechts beperkt relevant voor RVO's klimaatadaptatie-opgave."
    return "Niet relevant voor RVO's klimaatadaptatie-opgave."


def render_tag_pills(values: list[str], muted: bool = False) -> None:
    """Render compact tag pills for opgaven/transities."""
    if not values:
        return
    pill_class = "tag-pill tag-pill-muted" if muted else "tag-pill"
    pills = "".join([f"<span class='{pill_class}'>{html.escape(value)}</span>" for value in values])
    st.markdown(pills, unsafe_allow_html=True)


@st.cache_data(ttl=86400, show_spinner=False)
def get_placeholder_image_data_uri() -> str:
    """Return data URI for bundled climate placeholder image."""
    placeholder_path = os.path.join(config.BASE_DIR, "assets", "climate_placeholder.svg")
    with open(placeholder_path, "rb") as f:
        encoded = b64encode(f.read()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


@st.cache_data(ttl=60)
def get_unique_keyword_tags() -> list[str]:
    """Get all distinct keyword tags currently present in the database."""
    all_tags: set[str] = set()
    with get_session() as session:
        rows = session.query(Document.keyword_tags).filter(Document.keyword_tags != None).all()
        for (raw_tags,) in rows:
            all_tags.update(parse_keyword_tags(raw_tags))
    return sorted(all_tags)


def load_documents_filtered(
    search_query: str = "",
    sources: list[str] = None,
    doc_types: list[str] = None,
    status_filter: str = "Alle",
    has_pdf_filter: str = "Alle",
    selected_tags: list[str] = None,
    tags_match_mode: str = "all",
    date_from: datetime = None,
    date_to: datetime = None,
    limit: int = 500
) -> list[dict]:
    """Load documents with filters."""
    with get_session() as session:
        query = session.query(Document)
        
        # Search filter
        if search_query:
            search = f"%{search_query}%"
            query = query.filter(
                or_(
                    Document.title.ilike(search),
                    Document.full_text.ilike(search),
                    Document.source_name.ilike(search)
                )
            )
        
        # Source filter (multiselect)
        if sources and len(sources) > 0:
            query = query.filter(Document.source_name.in_(sources))

        if doc_types and len(doc_types) > 0:
            query = query.filter(Document.doc_type.in_(doc_types))
        
        # Status filter
        if status_filter != "Alle":
            query = query.filter(Document.processing_status == status_filter)
        
        # PDF filter
        if has_pdf_filter == "Met PDF":
            query = query.filter(Document.local_file_path != None)
        elif has_pdf_filter == "Zonder PDF":
            query = query.filter(Document.local_file_path == None)
        
        # Date range filter
        if date_from:
            query = query.filter(Document.publication_date >= date_from)
        if date_to:
            # Add one day to include the end date fully
            query = query.filter(Document.publication_date <= date_to)
        
        # Sort by publication_date descending, with nulls last
        docs = query.order_by(
            Document.publication_date.desc().nullslast()
        ).all()

        data = []
        for doc in docs:
            doc_tags = parse_keyword_tags(doc.keyword_tags)
            data.append({
                "id": doc.id,
                "title": doc.title,
                "source_name": doc.source_name,
                "doc_type": doc.doc_type,
                "content_type": doc.content_type,
                "publication_date": doc.publication_date,
                "fetched_at": doc.fetched_at,
                "processing_status": doc.processing_status,
                "local_file_path": doc.local_file_path,
                "thumbnail_url": doc.thumbnail_url,
                "url": doc.url,
                "full_text": doc.full_text,
                "has_summary": bool(doc.ai_summary),
                "has_tasks": bool(doc.ai_tasks_json),
                "keyword_tags": doc_tags,
            })

        # Tags filter is applied after base DB filters.
        if selected_tags:
            selected_set = {t.strip().lower() for t in selected_tags if t and t.strip()}
            if selected_set:
                if tags_match_mode == "all":
                    data = [
                        d for d in data
                        if selected_set.issubset(set(d["keyword_tags"]))
                    ]
                else:
                    data = [
                        d for d in data
                        if set(d["keyword_tags"]).intersection(selected_set)
                    ]

        return data[:limit]


def load_file_content(filepath: str) -> str:
    """Load content from a text file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Fout bij laden bestand: {e}"


def save_file_content(filepath: str, content: str) -> bool:
    """Save content to a text file."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        st.error(f"Fout bij opslaan: {e}")
        return False


def get_document_details(doc_id: int) -> dict:
    """Get full document details."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if doc:
            return {
                "id": doc.id,
                "title": doc.title,
                "url": doc.url,
                "source_name": doc.source_name,
                "doc_type": doc.doc_type,
                "publication_date": doc.publication_date,
                "fetched_at": doc.fetched_at,
                "content_type": doc.content_type,
                "local_file_path": doc.local_file_path,
                "thumbnail_url": doc.thumbnail_url,
                "full_text": doc.full_text,
                "cleaned_text": doc.cleaned_text,
                "processing_status": doc.processing_status,
                "is_relevant": doc.is_relevant,
                "screening_status": doc.screening_status,
                "screening_requested_at": doc.screening_requested_at,
                "screened_at": doc.screened_at,
                "screening_model": doc.screening_model,
                "screening_input_json": doc.screening_input_json,
                "screening_output_json": doc.screening_output_json,
                "screening_error": doc.screening_error,
                "ai_summary": doc.ai_summary,
                "ai_tasks_json": doc.ai_tasks_json,
            }
    return None


def get_sample_documents(limit: int = 100) -> list[dict]:
    """Return recent documents for prompt studio sample selection."""
    with get_session() as session:
        docs = (
            session.query(Document)
            .filter((Document.cleaned_text != None) | (Document.full_text != None))
            .order_by(Document.publication_date.desc().nullslast(), Document.id.desc())
            .limit(limit)
            .all()
        )

        data: list[dict] = []
        for doc in docs:
            data.append(
                {
                    "id": doc.id,
                    "title": doc.title or f"Document {doc.id}",
                "source_name": doc.source_name,
                "doc_type": doc.doc_type,
                "publication_date": doc.publication_date,
                    "url": doc.url,
                    "content_type": doc.content_type,
                    "discovery_method": doc.discovery_method,
                    "full_text": doc.full_text,
                    "cleaned_text": doc.cleaned_text,
                    "keyword_tags": doc.keyword_tags,
                    "local_file_path": doc.local_file_path,
                }
            )
        return data


def _format_sample_document_label(doc: dict) -> str:
    date_label = doc["publication_date"].strftime("%d-%m-%Y") if doc.get("publication_date") else "Onbekend"
    source_label = doc.get("source_name") or "Onbekende bron"
    title_label = doc.get("title") or f"Document {doc.get('id')}"
    return f"{doc['id']} | {date_label} | {source_label} | {title_label[:90]}"


def save_ai_summary(doc_id: int, summary: str) -> bool:
    """Save AI summary to database."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.ai_summary = summary
            if doc.ai_tasks_json:
                doc.processing_status = "analyzed"
            session.commit()
            return True
    return False


def save_ai_tasks(doc_id: int, tasks_json: str) -> bool:
    """Save AI tasks JSON to database."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.ai_tasks_json = tasks_json
            if doc.ai_summary:
                doc.processing_status = "analyzed"
            session.commit()
            return True
    return False


def render_card(doc: dict) -> str:
    """Build HTML for a single document card."""
    title_raw = doc.get("title") or "Geen titel"
    title = title_raw
    date_str = doc["publication_date"].strftime("%d-%m-%Y") if doc.get("publication_date") else "Onbekend"
    author = doc.get("source_name") or "Onbekend"
    doc_type = doc.get("doc_type") or "onbekend"
    summary = build_card_summary(doc.get("full_text"), source_name=author, publication_date=doc.get("publication_date"))
    thumb_url = doc.get("thumbnail_url") or get_placeholder_image_data_uri()
    visible_tags, overflow = get_tier1_tag_chips(doc.get("keyword_tags", []))
    tags_html = "".join([f"<span class='card-tag'>{html.escape(tag)}</span>" for tag in visible_tags])
    if overflow > 0:
        tags_html += f"<span class='card-tag card-tag-overflow'>+{overflow}</span>"

    doc_id = int(doc["id"])
    auth_token = st.session_state.get("auth_token")
    href = f"?open_doc={doc_id}"
    if auth_token:
        href += f"&a={quote_plus(str(auth_token))}"
    return textwrap.dedent(f"""
    <article class="card-shell">
        <img class="card-thumb" src="{html.escape(thumb_url)}" alt="thumbnail">
        <div class="card-content">
            <div class="card-tags">{tags_html}</div>
            <div class="card-meta">{html.escape(date_str)} / {html.escape(author)} / {html.escape(doc_type)}</div>
            <div class="card-title">{html.escape(title)}</div>
            <div class="card-summary">{html.escape(summary)}</div>
        </div>
        <div class="card-cta-wrap">
            <a class="card-cta" href="{href}" target="_self">
                <span>details</span>
                <span class="card-cta-icon">&#8250;</span>
            </a>
        </div>
    </article>
    """).strip()


def render_cards_grid(docs: list[dict]) -> None:
    """Render cards in an adaptive CSS grid with stable readable card widths."""
    cards_html = "".join(render_card(doc) for doc in docs)
    st.markdown(f'<div class="card-grid">{cards_html}</div>', unsafe_allow_html=True)


def consume_open_doc_query_param() -> None:
    """Open document detail when card CTA sets ?open_doc=<id>."""
    open_doc = st.query_params.get("open_doc")
    if not open_doc:
        return
    try:
        doc_id = int(str(open_doc))
    except Exception:
        del st.query_params["open_doc"]
        return
    st.session_state.selected_doc_id = doc_id
    st.session_state.show_detail = True
    st.session_state.detail_subview = "main"
    st.session_state.detail_advanced_focus = None
    del st.query_params["open_doc"]
    st.rerun()


def render_document_detail(doc_id: int):
    """Render the document detail view with reader-first main screen and advanced subview."""
    doc = get_document_details(doc_id)
    if not doc:
        st.error(f"Document {doc_id} niet gevonden")
        return

    detail_view = st.session_state.get("detail_subview", "main")
    advanced_focus = st.session_state.get("detail_advanced_focus")
    screening_output = parse_screening_output(doc.get("screening_output_json"))
    thumbnail_url = doc.get("thumbnail_url") or get_placeholder_image_data_uri()
    source_label = doc.get("source_name") or "Onbekende bron"
    doc_type_label = doc.get("doc_type") or "onbekend"
    publication_label = format_detail_date(doc.get("publication_date"))
    score = screening_output.get("climate_adaptation_relevance_score") if screening_output else None
    score_badge_class = get_score_badge_class(score)

    if st.button("← Terug naar overzicht"):
        st.session_state.show_detail = False
        st.session_state.detail_subview = "main"
        st.session_state.detail_advanced_focus = None
        st.rerun()

    if detail_view == "advanced":
        top_cols = st.columns([1, 1, 4])
        with top_cols[0]:
            if st.button("← Hoofdweergave", use_container_width=True):
                st.session_state.detail_subview = "main"
                st.session_state.detail_advanced_focus = None
                st.rerun()
        with top_cols[1]:
            if doc.get("local_file_path") and os.path.exists(doc["local_file_path"]):
                with open(doc["local_file_path"], "rb") as f:
                    st.download_button(
                        "⬇️ PDF",
                        f.read(),
                        file_name=os.path.basename(doc["local_file_path"]),
                        mime="application/pdf",
                        use_container_width=True,
                    )
        st.subheader("Advanced")
        st.caption("Technische screeningweergave en broninspectie.")

        screening_input = build_screening_input(doc)
        llm_request = build_llm_screening_request(screening_input)
        llm_request_json = serialize_llm_screening_request(llm_request)
        llm_user_message = build_screening_user_message(llm_request)

        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("Screening status", doc.get("screening_status") or "niet gestart")
        with col_b:
            st.metric("Model", doc.get("screening_model") or "onbekend")
        with col_c:
            st.metric("Excerpt woorden", count_words(screening_input.excerpt_text))
        with col_d:
            confidence_value = screening_output.get("confidence") if screening_output else None
            st.metric("Confidence", f"{confidence_value:.2f}" if isinstance(confidence_value, (int, float)) else "n.v.t.")

        with st.expander("Volledige tekst", expanded=advanced_focus == "full_text"):
            if doc['full_text']:
                st.text_area("Volledige tekst", doc['full_text'][:20000], height=360, disabled=True)
                if len(doc['full_text']) > 20000:
                    st.caption(f"... en nog {len(doc['full_text']) - 20000} karakters")
            else:
                st.info("Geen tekst beschikbaar.")

        with st.expander("PDF", expanded=advanced_focus == "pdf"):
            if doc['local_file_path']:
                st.success(f"PDF beschikbaar: `{doc['local_file_path']}`")
                if os.path.exists(doc['local_file_path']):
                    with open(doc['local_file_path'], "rb") as f:
                        st.download_button(
                            "⬇️ Download PDF",
                            f.read(),
                            file_name=os.path.basename(doc['local_file_path']),
                            mime="application/pdf"
                        )
            else:
                st.info("Geen PDF gekoppeld aan dit document.")

        with st.expander("Screening excerpt preview", expanded=advanced_focus == "excerpt"):
            if screening_input.excerpt_text:
                st.text_area(
                    "Geselecteerde screeningtekst",
                    screening_input.excerpt_text,
                    height=320,
                    disabled=True,
                )
            else:
                st.info("Geen excerpt beschikbaar.")

        with st.expander("LLM input JSON", expanded=advanced_focus == "llm_json"):
            st.text_area(
                "Reduced request object",
                llm_request_json,
                height=220,
                disabled=True,
            )

        with st.expander("Final user message", expanded=advanced_focus == "user_message"):
            st.text_area(
                "User message zoals verstuurd naar de LLM",
                llm_user_message,
                height=260,
                disabled=True,
            )

        if doc.get("screened_at") or doc.get("screening_error"):
            with st.expander("Screening metadata", expanded=advanced_focus == "metadata"):
                st.write(f"**Status:** {doc.get('screening_status') or 'niet gestart'}")
                st.write(f"**Model:** {doc.get('screening_model') or 'onbekend'}")
                st.write(f"**Aangevraagd:** {doc['screening_requested_at'].strftime('%d-%m-%Y %H:%M') if doc.get('screening_requested_at') else 'Onbekend'}")
                st.write(f"**Gescreend:** {doc['screened_at'].strftime('%d-%m-%Y %H:%M') if doc.get('screened_at') else 'Onbekend'}")
                if doc.get("screening_error"):
                    st.error(doc["screening_error"])

        if doc["ai_summary"] or doc["ai_tasks_json"]:
            with st.expander("Legacy AI Output", expanded=False):
                if doc["ai_summary"]:
                    st.subheader("Samenvatting")
                    st.markdown(doc["ai_summary"])
                if doc["ai_tasks_json"]:
                    st.subheader("Oude Opgave Analyse")
                    try:
                        tasks = json.loads(doc["ai_tasks_json"])
                        if isinstance(tasks, dict) and tasks:
                            df = pd.DataFrame(
                                [{"Opgave": k, "Score": v} for k, v in tasks.items()]
                            ).sort_values("Score", ascending=False)
                            st.dataframe(df, use_container_width=True, hide_index=True)
                        else:
                            st.code(doc["ai_tasks_json"])
                    except json.JSONDecodeError:
                        st.code(doc["ai_tasks_json"])
        return

    header_cols = st.columns([4.2, 1.3], gap="large")
    with header_cols[0]:
        st.title(doc['title'] or "Geen titel")
        st.caption(f"{source_label} · {publication_label} · {doc_type_label} · {doc.get('content_type') or 'onbekend'}")
        if doc.get("url"):
            st.markdown(f"[{doc['url']}]({doc['url']})")
        action_cols = st.columns([1, 1, 0.9])
        with action_cols[0]:
            if st.button("Bekijk volledige tekst", use_container_width=True):
                st.session_state.detail_subview = "advanced"
                st.session_state.detail_advanced_focus = "full_text"
                st.rerun()
        with action_cols[1]:
            if st.button("Bekijk PDF", disabled=not bool(doc.get("local_file_path")), use_container_width=True):
                st.session_state.detail_subview = "advanced"
                st.session_state.detail_advanced_focus = "pdf"
                st.rerun()
        with action_cols[2]:
            if st.button("Advanced", use_container_width=True):
                st.session_state.detail_subview = "advanced"
                st.session_state.detail_advanced_focus = None
                st.rerun()
    with header_cols[1]:
        st.image(thumbnail_url, width=250)

    summary_text = None
    explanation_text = None
    primary_opgave = None
    related_opgaves: list[str] = []
    related_transities: list[str] = []
    cross_signal = "none"
    cross_explanation = "none"
    if screening_output:
        summary_text = screening_output.get("short_summary")
        explanation_text = screening_output.get("climate_adaptation_explanation")
        primary_opgave = screening_output.get("primary_opgave")
        related_opgaves = screening_output.get("related_opgaves") or []
        related_transities = screening_output.get("related_transities") or []
        cross_signal = screening_output.get("cross_domain_relevance_signal") or "none"
        cross_explanation = screening_output.get("cross_domain_explanation") or "none"

    st.markdown("---")

    if screening_output:
        summary_cols = st.columns([2.8, 1.2], gap="large")
        with summary_cols[0]:
            st.markdown("<div class='detail-kicker'>Korte samenvatting</div>", unsafe_allow_html=True)
            st.write(summary_text)
        with summary_cols[1]:
            st.metric("Klimaatadaptatie relevantie", f"{score}/10")
            st.markdown(
                f"<span class='score-badge {score_badge_class}'>{html.escape(get_score_interpretation(score))}</span>",
                unsafe_allow_html=True,
            )
            confidence_value = screening_output.get("confidence")
            if isinstance(confidence_value, (int, float)):
                st.caption(f"Confidence: {confidence_value:.2f}")
    else:
        st.info("Nog geen screeningsresultaat beschikbaar voor dit document.")

    st.markdown("---")

    main_cols = st.columns([2.0, 1], gap="large")
    with main_cols[0]:
        st.subheader("Waarom relevant?")
        if explanation_text:
            st.write(explanation_text)
        else:
            st.write("Nog geen toelichting beschikbaar.")

        st.markdown("")
        st.subheader("Relevantie voor andere opgaven en transities")
        if primary_opgave:
            st.markdown("<div class='detail-kicker'>Primaire opgave</div>", unsafe_allow_html=True)
            render_tag_pills([primary_opgave])
        if related_opgaves:
            st.markdown("<div class='detail-kicker'>Gerelateerde opgaven</div>", unsafe_allow_html=True)
            render_tag_pills(related_opgaves)
        if related_transities:
            st.markdown("<div class='detail-kicker'>Gerelateerde transities</div>", unsafe_allow_html=True)
            render_tag_pills(related_transities, muted=True)
        if cross_signal in {"possible", "clear"} and cross_explanation and cross_explanation != "none":
            st.markdown("<div class='detail-kicker'>Cross-opgave toelichting</div>", unsafe_allow_html=True)
            st.write(cross_explanation)
        elif screening_output:
            st.caption("Geen duidelijke cross-opgave koppeling.")
        else:
            st.write("Nog geen screeningsanalyse beschikbaar.")
    with main_cols[1]:
        st.subheader("Documentgegevens")
        st.write(f"**Bron:** {source_label}")
        st.write(f"**Publicatiedatum:** {publication_label}")
        st.write(f"**Documenttype:** {doc_type_label}")
        st.write(f"**Type:** {doc.get('content_type') or 'Onbekend'}")
        st.write(f"**PDF beschikbaar:** {'Ja' if doc.get('local_file_path') else 'Nee'}")
        st.write(f"**Screening status:** {doc.get('screening_status') or 'Niet gestart'}")
        if doc.get("screened_at"):
            st.write(f"**Gescreend op:** {doc['screened_at'].strftime('%d-%m-%Y %H:%M')}")


# =============================================================================
# AUTHENTICATION GATE
# =============================================================================
ensure_auth_state_initialized()
restore_auth_from_query_params()

if not auth_config_valid():
    st.error(
        "Loginconfiguratie ontbreekt. Stel de omgevingsvariabelen "
        "`KA_DASHBOARD_USERNAME` en `KA_DASHBOARD_PASSWORD` in."
    )
    st.stop()

if not st.session_state.authenticated:
    render_login_screen()
    st.stop()

# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================
st.sidebar.title("🌍 Klimaatadaptatie KB")
render_logout_control()
page = st.sidebar.radio(
    "Navigatie",
    ["📚 Documenten", "🏛️ Rijksoverheid", "🔤 Zoektermen", "📡 RSS Feeds", "💬 Prompt Manager", "▶️ Pipeline"]
)

# =============================================================================
# MAIN CONTENT
# =============================================================================

if page == "📚 Documenten":
    st.title("Documentbrowser")
    consume_open_doc_query_param()
    
    # Check if we should show detail view
    if st.session_state.get("show_detail") and st.session_state.get("selected_doc_id"):
        render_document_detail(st.session_state.selected_doc_id)
    else:
        # ==========================================================================
        # SEARCH BAR
        # ==========================================================================
        search_query = st.text_input(
            "🔍 Zoeken",
            placeholder="Zoek op titel, inhoud of bron...",
            label_visibility="collapsed"
        )
        
        # ==========================================================================
        # FILTER CONTROLS
        # ==========================================================================
        if st.session_state.get("filter_tags_match_label") == "Any (Aanbevolen)":
            st.session_state.filter_tags_match_label = "Any"

        with st.expander("🎛️ Filters", expanded=False):
            col_source, col_status, col_pdf = st.columns(3)

            with col_source:
                all_sources = get_unique_sources()
                selected_sources = st.multiselect(
                    "📁 Bron",
                    options=all_sources,
                    default=[],
                    placeholder="Alle bronnen",
                    key="filter_sources",
                )

            with col_status:
                status_filter = st.radio(
                    "📊 Status",
                    ["Alle", "new", "analyzed"],
                    horizontal=True,
                    key="filter_status",
                )

            with col_pdf:
                pdf_filter = st.radio(
                    "📄 PDF",
                    ["Alle", "Met PDF", "Zonder PDF"],
                    horizontal=True,
                    key="filter_pdf",
                )

            # Date range + tags
            col_date1, col_date2, col_tags, col_doc_type = st.columns(4)
            with col_date1:
                date_from = st.date_input(
                    "📅 Datum van",
                    value=None,
                    format="DD-MM-YYYY",
                    key="filter_date_from",
                )
            with col_date2:
                date_to = st.date_input(
                    "📅 Datum tot",
                    value=None,
                    format="DD-MM-YYYY",
                    key="filter_date_to",
                )
            with col_tags:
                available_tags = get_unique_keyword_tags()
                selected_tags = st.multiselect(
                    "🏷️ Tags",
                    options=available_tags,
                    default=[],
                    placeholder="Alle tags",
                    key="filter_tags",
                )
                st.caption(f"{len(selected_tags)} tags geselecteerd")

                if hasattr(st, "popover"):
                    with st.popover("Meer filters"):
                        tags_mode_label = st.radio(
                            "Tag match",
                            ["All (Aanbevolen)", "Any"],
                            key="filter_tags_match_label",
                        )
                else:
                    with st.expander("Meer filters", expanded=False):
                        tags_mode_label = st.radio(
                            "Tag match",
                            ["All (Aanbevolen)", "Any"],
                            key="filter_tags_match_label",
                        )
                tags_match_mode = "any" if tags_mode_label == "Any" else "all"
            with col_doc_type:
                available_doc_types = get_unique_doc_types()
                selected_doc_types = st.multiselect(
                    "🏛️ Documenttype",
                    options=available_doc_types,
                    default=[],
                    placeholder="Alle types",
                    key="filter_doc_types",
                )
        
        # ==========================================================================
        # VIEW SWITCHER
        # ==========================================================================
        col_view, col_limit = st.columns([6, 1])
        with col_view:
                view_mode = st.radio(
                    "Weergave",
                    ["📋 Lijst", "🃏 Kaarten"],
                    horizontal=True,
                    label_visibility="collapsed"
                )
        with col_limit:
            limit = st.selectbox(
                "Max resultaten",
                [100, 200, 500, 1000],
                index=2,
                key="filter_limit",
            )
        
        # Convert date inputs to datetime
        date_from_dt = datetime.combine(date_from, datetime.min.time()) if date_from else None
        date_to_dt = datetime.combine(date_to, datetime.max.time()) if date_to else None
        
        # Load documents with filters
        docs = load_documents_filtered(
            search_query=search_query,
            sources=selected_sources if selected_sources else None,
            doc_types=selected_doc_types if selected_doc_types else None,
            status_filter=status_filter,
            has_pdf_filter=pdf_filter,
            selected_tags=selected_tags if selected_tags else None,
            tags_match_mode=tags_match_mode,
            date_from=date_from_dt,
            date_to=date_to_dt,
            limit=limit
        )

        active_filters = []
        if selected_sources:
            if len(selected_sources) == 1:
                active_filters.append(f"Bron: {selected_sources[0]}")
            else:
                active_filters.append(f"Bronnen: {selected_sources[0]} +{len(selected_sources) - 1}")
        if status_filter != "Alle":
            active_filters.append(f"Status: {status_filter}")
        if pdf_filter != "Alle":
            active_filters.append(f"PDF: {pdf_filter}")
        if selected_doc_types:
            if len(selected_doc_types) == 1:
                active_filters.append(f"Type: {selected_doc_types[0]}")
            else:
                active_filters.append(f"Types: {selected_doc_types[0]} +{len(selected_doc_types) - 1}")
        if date_from:
            active_filters.append(f"Van: {date_from.strftime('%d-%m-%Y')}")
        if date_to:
            active_filters.append(f"Tot: {date_to.strftime('%d-%m-%Y')}")
        if selected_tags:
            if len(selected_tags) == 1:
                active_filters.append(f"Tags: {selected_tags[0]}")
            else:
                active_filters.append(f"Tags: {selected_tags[0]} +{len(selected_tags) - 1}")
            active_filters.append(f"Tag match: {'All' if tags_match_mode == 'all' else 'Any'}")

        if active_filters:
            col_chips, col_reset = st.columns([6, 1])
            with col_chips:
                st.caption(" | ".join(active_filters))
            with col_reset:
                if st.button("Wis filters", use_container_width=True):
                    st.session_state.filter_sources = []
                    st.session_state.filter_status = "Alle"
                    st.session_state.filter_pdf = "Alle"
                    st.session_state.filter_date_from = None
                    st.session_state.filter_date_to = None
                    st.session_state.filter_tags = []
                    st.session_state.filter_doc_types = []
                    st.session_state.filter_tags_match_label = "All (Aanbevolen)"
                    st.session_state.filter_limit = 500
                    st.rerun()
        
        if not docs:
            st.info("Geen documenten gevonden. Pas de filters aan of voer de pipeline uit.")
        else:
            st.caption(f"Toont **{len(docs)}** documenten - Klik op een rij om details te openen")
            
            if view_mode == "📋 Lijst":
                # --- LIST VIEW with clickable rows ---
                df_data = []
                doc_ids = []  # Track IDs for row selection
                
                for doc in docs:
                    ai_status = ""
                    if doc["has_summary"] and doc["has_tasks"]:
                        ai_status = "✅ Compleet"
                    elif doc["has_summary"] or doc["has_tasks"]:
                        ai_status = "⏳ Deels"
                    else:
                        ai_status = "❌ Geen"
                    
                    doc_ids.append(doc["id"])
                    df_data.append({
                        "Datum": doc["publication_date"].strftime("%Y-%m-%d") if doc["publication_date"] else "",
                        "Titel": doc["title"] or "Geen titel",
                        "Bron": doc["source_name"] or "",
                        "Doc type": doc["doc_type"] or "",
                        "Status": doc["processing_status"],
                        "PDF": "✅" if doc["local_file_path"] else "❌",
                        "AI": ai_status
                    })
                
                df = pd.DataFrame(df_data)
                
                # Configure columns
                column_config = {
                    "Datum": st.column_config.TextColumn("Datum", width="small"),
                    "Titel": st.column_config.TextColumn("Titel", width="large"),
                    "Bron": st.column_config.TextColumn("Bron", width="medium"),
                    "Doc type": st.column_config.TextColumn("Doc type", width="medium"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "PDF": st.column_config.TextColumn("PDF", width="small"),
                    "AI": st.column_config.TextColumn("AI", width="small")
                }
                
                # Display dataframe with single-row selection
                event = st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config,
                    height=500,
                    on_select="rerun",
                    selection_mode="single-row"
                )
                
                # Handle row selection - auto-navigate to detail view
                if event.selection and event.selection.rows:
                    selected_row_idx = event.selection.rows[0]
                    selected_doc_id = doc_ids[selected_row_idx]
                    st.session_state.selected_doc_id = selected_doc_id
                    st.session_state.show_detail = True
                    st.session_state.detail_subview = "main"
                    st.session_state.detail_advanced_focus = None
                    st.rerun()
            
            else:
                # --- CARD VIEW ---
                render_cards_grid(docs)


elif page == "🏛️ Rijksoverheid":
    st.title("Rijksoverheid Monitor")
    consume_open_doc_query_param()

    if st.session_state.get("show_detail") and st.session_state.get("selected_doc_id"):
        render_document_detail(st.session_state.selected_doc_id)
    else:
        rijksoverheid_sources, parliament_sources = get_rijksoverheid_source_groups()
        st.caption("Voorgefilterd op alle geconfigureerde Rijksoverheid RSS-feeds, met extra parlement-focus.")

        ro_search_query = st.text_input(
            "🔍 Zoek in Rijksoverheid",
            placeholder="Zoek op titel, inhoud of bron...",
            label_visibility="collapsed",
            key="ro_search_query",
        )

        with st.expander("🎛️ Rijksoverheid filters", expanded=True):
            col_quick, col_source, col_doc_type = st.columns(3)
            with col_quick:
                parliament_only = st.checkbox(
                    "Alleen parlement-relevante stroom",
                    value=False,
                    key="ro_parliament_only",
                    help="Beperk tot Kamerstukken-bronnen en parlementaire documenttypen.",
                )
            with col_source:
                selected_ro_sources = st.multiselect(
                    "📁 Bron",
                    options=rijksoverheid_sources,
                    default=rijksoverheid_sources,
                    key="ro_filter_sources",
                )
            with col_doc_type:
                ro_doc_types = st.multiselect(
                    "🏛️ Documenttype",
                    options=get_unique_doc_types(),
                    default=[],
                    key="ro_filter_doc_types",
                )

            col_status, col_pdf, col_date1, col_date2 = st.columns(4)
            with col_status:
                ro_status_filter = st.radio(
                    "📊 Status",
                    ["Alle", "new", "analyzed"],
                    horizontal=True,
                    key="ro_filter_status",
                )
            with col_pdf:
                ro_pdf_filter = st.radio(
                    "📄 PDF",
                    ["Alle", "Met PDF", "Zonder PDF"],
                    horizontal=True,
                    key="ro_filter_pdf",
                )
            with col_date1:
                ro_date_from = st.date_input(
                    "📅 Datum van",
                    value=None,
                    format="DD-MM-YYYY",
                    key="ro_filter_date_from",
                )
            with col_date2:
                ro_date_to = st.date_input(
                    "📅 Datum tot",
                    value=None,
                    format="DD-MM-YYYY",
                    key="ro_filter_date_to",
                )

        ro_source_scope = list(selected_ro_sources or rijksoverheid_sources)
        if parliament_only:
            ro_source_scope = [name for name in ro_source_scope if name in parliament_sources]
            ro_doc_type_scope = ro_doc_types or sorted(PARLIAMENT_DOC_TYPES)
        else:
            ro_doc_type_scope = ro_doc_types or None

        ro_date_from_dt = datetime.combine(ro_date_from, datetime.min.time()) if ro_date_from else None
        ro_date_to_dt = datetime.combine(ro_date_to, datetime.max.time()) if ro_date_to else None

        ro_docs = load_documents_filtered(
            search_query=ro_search_query,
            sources=ro_source_scope,
            doc_types=ro_doc_type_scope,
            status_filter=ro_status_filter,
            has_pdf_filter=ro_pdf_filter,
            date_from=ro_date_from_dt,
            date_to=ro_date_to_dt,
            limit=500,
        )

        doc_type_counts: dict[str, int] = {}
        for doc in ro_docs:
            label = doc.get("doc_type") or "onbekend"
            doc_type_counts[label] = doc_type_counts.get(label, 0) + 1

        stat_cols = st.columns(4)
        stat_cols[0].metric("Documenten", len(ro_docs))
        stat_cols[1].metric("Bronnen", len(set(doc["source_name"] for doc in ro_docs if doc.get("source_name"))))
        stat_cols[2].metric("Met PDF", sum(1 for doc in ro_docs if doc.get("local_file_path")))
        stat_cols[3].metric("Types", len(doc_type_counts))

        if doc_type_counts:
            sorted_types = sorted(doc_type_counts.items(), key=lambda item: (-item[1], item[0]))
            st.caption("Meest voorkomende documenttypen: " + " | ".join(f"{name}: {count}" for name, count in sorted_types[:8]))

        if not ro_docs:
            st.info("Geen Rijksoverheid-documenten gevonden voor deze selectie.")
        else:
            ro_view_mode = st.radio(
                "Weergave",
                ["📋 Lijst", "🃏 Kaarten"],
                horizontal=True,
                key="ro_view_mode",
                label_visibility="collapsed",
            )

            if ro_view_mode == "📋 Lijst":
                df_data = []
                doc_ids = []
                for doc in ro_docs:
                    doc_ids.append(doc["id"])
                    df_data.append(
                        {
                            "Datum": doc["publication_date"].strftime("%Y-%m-%d") if doc["publication_date"] else "",
                            "Titel": doc["title"] or "Geen titel",
                            "Bron": doc["source_name"] or "",
                            "Doc type": doc["doc_type"] or "",
                            "PDF": "✅" if doc["local_file_path"] else "❌",
                        }
                    )
                ro_df = pd.DataFrame(df_data)
                ro_event = st.dataframe(
                    ro_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Datum": st.column_config.TextColumn("Datum", width="small"),
                        "Titel": st.column_config.TextColumn("Titel", width="large"),
                        "Bron": st.column_config.TextColumn("Bron", width="medium"),
                        "Doc type": st.column_config.TextColumn("Doc type", width="medium"),
                        "PDF": st.column_config.TextColumn("PDF", width="small"),
                    },
                    height=520,
                    on_select="rerun",
                    selection_mode="single-row",
                )
                if ro_event.selection and ro_event.selection.rows:
                    selected_row_idx = ro_event.selection.rows[0]
                    st.session_state.selected_doc_id = doc_ids[selected_row_idx]
                    st.session_state.show_detail = True
                    st.session_state.detail_subview = "main"
                    st.session_state.detail_advanced_focus = None
                    st.rerun()
            else:
                render_cards_grid(ro_docs)


elif page == "🔤 Zoektermen":
    st.title("Zoekterm Configuratie")
    
    tab1, tab2, tab3 = st.tabs(["Tier 1 Zoektermen", "Tier 2 Zoektermen", "Contextwoorden"])
    
    with tab1:
        st.write("**Tier 1: Directe Treffer Zoektermen** - Documenten met deze worden altijd gedownload")
        tier1_path = os.path.join(config.BASE_DIR, "tier1_keywords.txt")
        tier1_content = load_file_content(tier1_path)
        
        new_tier1 = st.text_area(
            "Bewerk Tier 1 Zoektermen (één per regel, # voor opmerkingen)",
            tier1_content,
            height=400
        )
        
        if st.button("Opslaan Tier 1"):
            if save_file_content(tier1_path, new_tier1):
                st.success("Tier 1 zoektermen opgeslagen!")
    
    with tab2:
        st.write("**Tier 2: Contextafhankelijke Zoektermen** - Alleen gedownload met contextwoorden")
        tier2_path = os.path.join(config.BASE_DIR, "tier2_keywords.txt")
        tier2_content = load_file_content(tier2_path)
        
        new_tier2 = st.text_area(
            "Bewerk Tier 2 Zoektermen ([Thema] koppen, één zoekterm per regel)",
            tier2_content,
            height=400
        )
        
        if st.button("Opslaan Tier 2"):
            if save_file_content(tier2_path, new_tier2):
                st.success("Tier 2 zoektermen opgeslagen!")
    
    with tab3:
        st.write("**Contextwoorden** - Maak Tier 2 zoektermen relevant")
        context_path = os.path.join(config.BASE_DIR, "context_words.txt")
        context_content = load_file_content(context_path)
        
        new_context = st.text_area(
            "Bewerk Contextwoorden (één per regel)",
            context_content,
            height=300
        )
        
        if st.button("Opslaan Contextwoorden"):
            if save_file_content(context_path, new_context):
                st.success("Contextwoorden opgeslagen!")


elif page == "📡 RSS Feeds":
    st.title("Bron Configuratie")

    sources, sources_error, sources_path = config.load_sources_with_status()
    if sources_error:
        st.warning(sources_error)

    st.info(f"Momenteel geconfigureerd: **{len(sources)} bronnen**")
    st.caption(f"Bronbestand: `{sources_path}`")

    with st.expander("Bekijk Huidige Bronnen"):
        if not sources:
            st.write("Geen actieve bronnen gevonden.")
        for source in sources:
            method = source.get("method", "rss")
            source_name = source.get("source_name", "Unknown")
            url = source.get("url", "")
            st.text(f"[{method}] {source_name}: {url}")


elif page == "💬 Prompt Manager":
    st.title("Screening Prompt Studio")
    st.write("Beheer de screening-prompts en bekijk exact welke request-shape straks naar de LLM gaat.")

    prompts = config.load_prompts()

    screening_system_context = st.text_area(
        "1. System Context",
        value=prompts.get("screening_system_context", ""),
        height=180,
        help="RVO-perspectief, klimaatadaptatie als ankerlens en interpretatiekader.",
    )
    screening_task_instructions = st.text_area(
        "2. Task Instructions",
        value=prompts.get("screening_task_instructions", ""),
        height=180,
        help="Wat het model precies moet doen met de bron en welke nadruk de samenvatting moet leggen.",
    )
    screening_output_contract = st.text_area(
        "3. Output Contract",
        value=prompts.get("screening_output_contract", ""),
        height=200,
        help="Strikte JSON-outputregels en gecontroleerde labels voor opgaven en transities.",
    )

    compiled_prompt = compile_screening_system_prompt(
        {
            "screening_system_context": screening_system_context,
            "screening_task_instructions": screening_task_instructions,
            "screening_output_contract": screening_output_contract,
        }
    )

    if st.button("💾 Opslaan Screening Prompts", type="primary"):
        new_prompts = dict(prompts)
        new_prompts.update(
            {
                "screening_system_context": screening_system_context,
                "screening_task_instructions": screening_task_instructions,
                "screening_output_contract": screening_output_contract,
            }
        )
        if config.save_prompts(new_prompts):
            st.success("Screening prompts opgeslagen!")
        else:
            st.error("Fout bij opslaan prompts")

    with st.expander("Compiled System Prompt", expanded=True):
        st.text_area(
            "Samengevoegde system prompt",
            compiled_prompt,
            height=320,
            disabled=True,
        )

    st.divider()
    st.subheader("Request Shape")
    st.caption("De screening-call bestaat uit een system prompt, een compacte JSON user payload en een strikte JSON response.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("`system`\n\n3 prompt chunks, samengevoegd in vaste volgorde.")
    with col2:
        st.info("`user`\n\nReduced JSON payload met titel, bron, datum, tags en excerpt.")
    with col3:
        st.info("`response`\n\nStrikte JSON volgens het screeningschema.")

    with st.expander("Response Schema", expanded=False):
        st.code(json.dumps(screening_output_schema(), ensure_ascii=False, indent=2), language="json")

    st.divider()
    st.subheader("Test on Sample Document")

    sample_docs = get_sample_documents()
    if not sample_docs:
        st.info("Geen documenten beschikbaar voor preview.")
    else:
        selected_index = st.selectbox(
            "Kies een voorbeeldbron",
            options=list(range(len(sample_docs))),
            format_func=lambda idx: _format_sample_document_label(sample_docs[idx]),
            index=0,
        )
        sample_doc = sample_docs[selected_index]
        screening_input = build_screening_input(sample_doc)
        llm_request = build_llm_screening_request(screening_input)
        llm_request_json = serialize_llm_screening_request(llm_request)
        llm_user_message = build_screening_user_message(llm_request)

        meta_a, meta_b, meta_c, meta_d = st.columns(4)
        with meta_a:
            st.metric("Document ID", sample_doc["id"])
        with meta_b:
            st.metric("Bron", sample_doc.get("source_name") or "Onbekend")
        with meta_c:
            st.metric("Excerpt strategie", screening_input.excerpt_strategy)
        with meta_d:
            st.metric("Woorden", count_words(screening_input.excerpt_text))

        with st.expander("Excerpt Preview", expanded=True):
            st.text_area(
                "Excerpt dat door de builder is geselecteerd",
                screening_input.excerpt_text,
                height=300,
                disabled=True,
            )

        with st.expander("LLM Input JSON", expanded=False):
            st.text_area(
                "Reduced request object",
                llm_request_json,
                height=220,
                disabled=True,
            )

        with st.expander("Final User Message", expanded=False):
            st.text_area(
                "User message zoals die naar de LLM zou gaan",
                llm_user_message,
                height=260,
                disabled=True,
            )

elif page == "▶️ Pipeline":
    st.title("Pipeline Uitvoeren")
    
    st.write("""
    Klik op de knop hieronder om de ingestie pipeline handmatig uit te voeren.
    Dit zal:
    1. Alle geconfigureerde bronnen ophalen (RSS/sitemap/listing)
    2. Filteren op zoektermen
    3. Relevante documenten downloaden
    4. Opslaan in database
    """)
    
    # Stats
    with get_session() as session:
        total_docs = session.query(Document).count()
        new_docs = session.query(Document).filter(Document.processing_status == "new").count()
        analyzed_docs = session.query(Document).filter(Document.processing_status == "analyzed").count()
        docs_with_pdf = session.query(Document).filter(Document.local_file_path != None).count()
        docs_without_pdf = total_docs - docs_with_pdf
        docs_with_summary = session.query(Document).filter(Document.ai_summary != None).count()
        docs_with_tasks = session.query(Document).filter(Document.ai_tasks_json != None).count()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Totaal", total_docs)
    col2.metric("Nieuw", new_docs)
    col3.metric("Geanalyseerd", analyzed_docs)
    col4.metric("Met PDF", docs_with_pdf)
    
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Zonder PDF", docs_without_pdf)
    col6.metric("Met Samenvatting", docs_with_summary)
    col7.metric("Met Opgaven", docs_with_tasks)
    col8.metric("Bronnen", len(config.load_sources()))
    
    st.subheader("Acties")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("▶️ Voer Pipeline Uit", type="primary"):
            with st.spinner("Pipeline uitvoeren..."):
                result = subprocess.run(
                    ["python", "main.py"],
                    capture_output=True,
                    text=True,
                    cwd=config.BASE_DIR
                )
                
                if result.returncode == 0:
                    st.success("Pipeline succesvol voltooid!")
                    st.code(result.stdout)
                else:
                    st.error("Pipeline mislukt!")
                    st.code(result.stderr)
    
    with col_b:
        if st.button("🔄 Herhaal Ontbrekende PDFs"):
            with st.spinner("Zoeken naar PDFs in bestaande documenten..."):
                result = subprocess.run(
                    ["python", "refetch_pdfs.py"],
                    capture_output=True,
                    text=True,
                    cwd=config.BASE_DIR
                )
                
                if result.returncode == 0:
                    st.success("PDF herhaling voltooid!")
                    st.code(result.stdout)
                else:
                    st.error("PDF herhaling mislukt!")
                    st.code(result.stderr)


# Footer
st.sidebar.markdown("---")
st.sidebar.caption(f"Database: `{config.DATABASE_PATH}`")
st.sidebar.caption(f"PDFs: `{config.PDF_STORAGE_PATH}`")


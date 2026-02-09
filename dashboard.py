"""
Climate Adaptation Knowledge Base - Dashboard

A Streamlit frontend to:
- Search and browse documents (list/card views)
- Edit zoektermen, feeds, and AI prompts
- Access PDF files
- Run the ingestion pipeline
- Human-in-the-loop AI workflow

Run with: streamlit run dashboard.py
"""

import json
import os
import subprocess
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import or_, func

from modules.database import get_session, Document, init_db
from modules.fetcher import ContentFetcher
import config

# Page config
st.set_page_config(
    page_title="Klimaatadaptatie KB",
    page_icon="🌍",
    layout="wide"
)

# Initialize database
init_db()

# Custom CSS for cards
st.markdown("""
<style>
.doc-card {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
    background: #fafafa;
}
.doc-card:hover {
    border-color: #1f77b4;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.doc-title {
    font-weight: bold;
    font-size: 1.1em;
    margin-bottom: 8px;
    color: #1f77b4;
}
.doc-meta {
    color: #666;
    font-size: 0.9em;
    margin-bottom: 4px;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
    margin-right: 4px;
}
.badge-new { background: #fff3cd; color: #856404; }
.badge-analyzed { background: #d4edda; color: #155724; }
.badge-failed { background: #f8d7da; color: #721c24; }
.badge-pdf { background: #cce5ff; color: #004085; }
</style>
""", unsafe_allow_html=True)


def get_unique_sources() -> list[str]:
    """Get unique source names from database."""
    with get_session() as session:
        sources = session.query(Document.source_name).distinct().all()
        return sorted([s[0] for s in sources if s[0]])


def load_documents_filtered(
    search_query: str = "",
    sources: list[str] = None,
    status_filter: str = "Alle",
    has_pdf_filter: str = "Alle",
    date_from: datetime = None,
    date_to: datetime = None,
    limit: int = 100
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
        ).limit(limit).all()
        
        data = []
        for doc in docs:
            data.append({
                "id": doc.id,
                "title": doc.title,
                "source_name": doc.source_name,
                "content_type": doc.content_type,
                "publication_date": doc.publication_date,
                "fetched_at": doc.fetched_at,
                "processing_status": doc.processing_status,
                "local_file_path": doc.local_file_path,
                "url": doc.url,
                "has_summary": bool(doc.ai_summary),
                "has_tasks": bool(doc.ai_tasks_json)
            })
        
        return data


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
                "publication_date": doc.publication_date,
                "fetched_at": doc.fetched_at,
                "content_type": doc.content_type,
                "local_file_path": doc.local_file_path,
                "full_text": doc.full_text,
                "processing_status": doc.processing_status,
                "is_relevant": doc.is_relevant,
                "ai_summary": doc.ai_summary,
                "ai_tasks_json": doc.ai_tasks_json,
            }
    return None


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


def render_card(doc: dict):
    """Render a document card."""
    with st.container():
        # Status badges
        badges = []
        if doc["processing_status"] == "new":
            badges.append("🆕 Nieuw")
        elif doc["processing_status"] == "analyzed":
            badges.append("✅ Geanalyseerd")
        elif doc["processing_status"] == "failed":
            badges.append("❌ Mislukt")
        
        if doc["local_file_path"]:
            badges.append("📄 PDF")
        
        if doc["has_summary"]:
            badges.append("📝 Samenvatting")
        if doc["has_tasks"]:
            badges.append("📊 Opgaven")
        
        badge_str = " | ".join(badges)
        
        # Format date
        date_str = ""
        if doc["publication_date"]:
            date_str = doc["publication_date"].strftime("%d-%m-%Y")
        
        col1, col2 = st.columns([4, 1])
        
        with col1:
            st.markdown(f"**{doc['title'][:100]}{'...' if doc['title'] and len(doc['title']) > 100 else ''}**")
            st.caption(f"🏢 {doc['source_name'] or 'Onbekend'} | 📅 {date_str} | {badge_str}")
        
        with col2:
            if st.button("📖 Details", key=f"card_{doc['id']}"):
                st.session_state.selected_doc_id = doc['id']
                st.session_state.show_detail = True
                st.rerun()
        
        st.divider()


def render_document_detail(doc_id: int):
    """Render the full document detail view with AI workflow."""
    doc = get_document_details(doc_id)
    if not doc:
        st.error(f"Document {doc_id} niet gevonden")
        return
    
    # Back button
    if st.button("← Terug naar overzicht"):
        st.session_state.show_detail = False
        st.rerun()
    
    st.header(doc['title'] or "Geen titel")
    
    # Meta info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**Bron:** {doc['source_name']}")
        st.write(f"**Type:** {doc['content_type']}")
    with col2:
        st.write(f"**Opgehaald:** {doc['fetched_at'].strftime('%d-%m-%Y %H:%M') if doc['fetched_at'] else 'Onbekend'}")
        st.write(f"**Status:** {doc['processing_status']}")
    with col3:
        st.write(f"**URL:** [{doc['url'][:40]}...]({doc['url']})")
    
    # PDF section
    st.subheader("📄 Document Bestand")
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
        st.warning("Geen PDF gekoppeld aan dit document")
        if st.button("🔍 Probeer PDF te vinden", key=f"refetch_{doc_id}"):
            with st.spinner("Zoeken naar PDF op pagina..."):
                fetcher = ContentFetcher()
                result = fetcher.fetch(doc['url'], doc['source_name'] or "Onbekend", doc['title'] or "")
                
                if result and result["file_path"]:
                    with get_session() as session:
                        db_doc = session.query(Document).filter(Document.id == doc_id).first()
                        if db_doc:
                            db_doc.content_type = result["type"]
                            db_doc.local_file_path = result["file_path"]
                            db_doc.full_text = result["text"]
                            session.commit()
                    
                    st.success(f"PDF gevonden en opgeslagen: {result['file_path']}")
                    st.rerun()
                else:
                    st.info("Geen PDF downloadlink gevonden op deze pagina")
    
    # Text preview
    with st.expander("📜 Volledige Tekst Voorvertoning", expanded=False):
        if doc['full_text']:
            st.text_area("", doc['full_text'][:10000], height=300, disabled=True)
            if len(doc['full_text']) > 10000:
                st.caption(f"... en nog {len(doc['full_text']) - 10000} karakters")
        else:
            st.info("Geen tekst beschikbaar")
    
    st.divider()
    
    # ==========================================================================
    # AI WORKFLOW SECTION
    # ==========================================================================
    st.header("🤖 AI Analyse Workflow")
    
    # Load prompts
    prompts = config.load_prompts()
    
    tab_summary, tab_tasks = st.tabs(["📝 Samenvatting", "📊 Opgave Analyse"])
    
    # --- SUMMARY TAB ---
    with tab_summary:
        st.subheader("Samenvatting")
        
        # Show existing summary if present
        if doc['ai_summary']:
            st.success("Samenvatting aanwezig")
            st.markdown(doc['ai_summary'])
            st.divider()
        
        # Prompt generation
        with st.expander("🔧 Genereer Prompt voor AI", expanded=not doc['ai_summary']):
            if st.button("📋 Genereer Samenvatting Prompt", key="gen_summary_prompt"):
                # #region agent log
                import json as json_module
                log_data_summary = {
                    "doc_id": doc_id,
                    "has_full_text": bool(doc.get('full_text')),
                    "full_text_length": len(doc.get('full_text') or '')
                }
                with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json_module.dumps({"location": "dashboard.py:355", "message": "Summary prompt button clicked", "data": log_data_summary, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "F"}) + "\n")
                # #endregion
                if doc['full_text']:
                    prompt_template = prompts.get("summary_prompt", "Maak een samenvatting van: {document_text}")
                    # #region agent log
                    log_data_summary2 = {
                        "prompt_template_length": len(prompt_template),
                        "has_placeholder": "{document_text}" in prompt_template,
                        "placeholder_count": prompt_template.count("{document_text}")
                    }
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:358", "message": "Summary prompt template check", "data": log_data_summary2, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "G"}) + "\n")
                    # #endregion
                    full_prompt = prompt_template.replace("{document_text}", doc['full_text'])
                    # #region agent log
                    log_data_summary3 = {
                        "full_prompt_length": len(full_prompt),
                        "replacement_happened": full_prompt != prompt_template,
                        "prompt_unchanged": full_prompt == prompt_template
                    }
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:359", "message": "Summary prompt after replacement", "data": log_data_summary3, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "H"}) + "\n")
                    # #endregion
                    # Store prompt with document-specific key to avoid stale data
                    st.session_state[f"summary_prompt_{doc_id}"] = full_prompt
                    st.rerun()  # Refresh to show updated prompt
                else:
                    st.error("Geen tekst beschikbaar om prompt mee te genereren")
            
            # Use document-specific key
            prompt_key = f"summary_prompt_{doc_id}"
            if prompt_key in st.session_state:
                char_count = len(st.session_state[prompt_key])
                st.info(f"📊 Prompt lengte: **{char_count:,}** karakters (~{char_count // 4:,} tokens)")
                st.text_area(
                    "Volledige prompt (selecteer alles met Ctrl+A, kopieer met Ctrl+C):",
                    st.session_state[prompt_key],
                    height=400,
                    key=f"summary_prompt_output_{doc_id}"
                )
                st.caption("💡 Tip: Gebruik Ctrl+A in het tekstveld hierboven om alles te selecteren, dan Ctrl+C om te kopiëren.")
        
        # Input section
        st.subheader("AI Output Invoeren")
        summary_input = st.text_area(
            "Plak hier de AI-gegenereerde samenvatting:",
            value=doc['ai_summary'] or "",
            height=200,
            key="summary_input"
        )
        
        if st.button("💾 Opslaan Samenvatting", type="primary", key="save_summary"):
            if summary_input.strip():
                if save_ai_summary(doc_id, summary_input.strip()):
                    st.success("Samenvatting opgeslagen!")
                    st.rerun()
                else:
                    st.error("Fout bij opslaan")
            else:
                st.warning("Voer eerst een samenvatting in")
    
    # --- TASKS TAB ---
    with tab_tasks:
        st.subheader("Opgave Analyse (21 NAS Opgaven)")
        
        # Show existing analysis if present
        if doc['ai_tasks_json']:
            st.success("Opgave analyse aanwezig")
            try:
                tasks = json.loads(doc['ai_tasks_json'])
                # Display as a table
                if tasks:
                    df = pd.DataFrame([
                        {"Opgave": k, "Score": v} 
                        for k, v in tasks.items()
                    ]).sort_values("Score", ascending=False)
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except json.JSONDecodeError:
                st.warning("Opgeslagen JSON kon niet worden geparsed")
                st.code(doc['ai_tasks_json'])
            st.divider()
        
        # Prompt generation
        with st.expander("🔧 Genereer Prompt voor AI", expanded=not doc['ai_tasks_json']):
            if st.button("📋 Genereer Opgave Analyse Prompt", key="gen_tasks_prompt"):
                # #region agent log
                import json as json_module
                log_data = {
                    "doc_id": doc_id,
                    "has_full_text": bool(doc.get('full_text')),
                    "full_text_type": type(doc.get('full_text')).__name__,
                    "full_text_length": len(doc.get('full_text') or ''),
                    "full_text_preview": (doc.get('full_text') or '')[:100] if doc.get('full_text') else None
                }
                with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json_module.dumps({"location": "dashboard.py:421", "message": "Button clicked - checking doc full_text", "data": log_data, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "A"}) + "\n")
                # #endregion
                if doc['full_text']:
                    prompt_template = prompts.get("relevance_prompt", "Analyseer de relevantie: {document_text}")
                    # #region agent log
                    log_data2 = {
                        "prompt_template_length": len(prompt_template),
                        "has_placeholder": "{document_text}" in prompt_template,
                        "placeholder_count": prompt_template.count("{document_text}"),
                        "prompt_template_preview": prompt_template[:200]
                    }
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:424", "message": "Before replacement - prompt template check", "data": log_data2, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "B"}) + "\n")
                    # #endregion
                    full_prompt = prompt_template.replace("{document_text}", doc['full_text'])
                    # #region agent log
                    doc_start_marker = "DOCUMENT:\n"
                    doc_start_idx = full_prompt.find(doc_start_marker)
                    doc_after_marker = full_prompt[doc_start_idx + len(doc_start_marker):doc_start_idx + len(doc_start_marker) + 200] if doc_start_idx >= 0 else "MARKER_NOT_FOUND"
                    log_data3 = {
                        "full_prompt_length": len(full_prompt),
                        "replacement_happened": full_prompt != prompt_template,
                        "full_prompt_preview": full_prompt[:300],
                        "doc_text_in_result": doc['full_text'][:100] in full_prompt if doc['full_text'] else False,
                        "doc_start_marker_found": doc_start_idx >= 0,
                        "text_after_document_marker": doc_after_marker,
                        "full_prompt_end": full_prompt[-200:] if len(full_prompt) > 200 else full_prompt
                    }
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:426", "message": "After replacement - checking result", "data": log_data3, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "C"}) + "\n")
                    # #endregion
                    # Store prompt with document-specific key to avoid stale data
                    st.session_state[f"tasks_prompt_{doc_id}"] = full_prompt
                    # #region agent log
                    log_data4 = {
                        "session_state_key": f"tasks_prompt_{doc_id}",
                        "stored_value_length": len(full_prompt),
                        "stored_value_preview": full_prompt[:200]
                    }
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:428", "message": "Stored in session_state", "data": log_data4, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "D"}) + "\n")
                    # #endregion
                    st.rerun()  # Refresh to show updated prompt
                else:
                    # #region agent log
                    with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                        f.write(json_module.dumps({"location": "dashboard.py:430", "message": "No full_text available", "data": {"doc_id": doc_id, "full_text_value": str(doc.get('full_text'))}, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "A"}) + "\n")
                    # #endregion
                    st.error("Geen tekst beschikbaar om prompt mee te genereren")
            
            # Use document-specific key
            tasks_prompt_key = f"tasks_prompt_{doc_id}"
            if tasks_prompt_key in st.session_state:
                # #region agent log
                import json as json_module
                stored_prompt = st.session_state[tasks_prompt_key]
                log_data5 = {
                    "session_state_key": tasks_prompt_key,
                    "stored_prompt_length": len(stored_prompt),
                    "has_placeholder": "{document_text}" in stored_prompt,
                    "stored_prompt_preview": stored_prompt[:300],
                    "has_doc_text": doc.get('full_text', '')[:50] in stored_prompt if doc.get('full_text') else False
                }
                with open(r"c:\dev\KA-database\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json_module.dumps({"location": "dashboard.py:434", "message": "Displaying prompt from session_state", "data": log_data5, "timestamp": __import__("time").time() * 1000, "runId": "run1", "hypothesisId": "E"}) + "\n")
                # #endregion
                char_count = len(st.session_state[tasks_prompt_key])
                st.info(f"📊 Prompt lengte: **{char_count:,}** karakters (~{char_count // 4:,} tokens)")
                st.text_area(
                    "Volledige prompt (selecteer alles met Ctrl+A, kopieer met Ctrl+C):",
                    st.session_state[tasks_prompt_key],
                    height=400,
                    key=f"tasks_prompt_output_{doc_id}"
                )
                st.caption("💡 Tip: Gebruik Ctrl+A in het tekstveld hierboven om alles te selecteren, dan Ctrl+C om te kopiëren.")
        
        # Input section
        st.subheader("AI Output Invoeren")
        st.caption("Verwacht formaat: JSON met opgave namen en scores, bijv. `{\"Wateroverlast\": 8, \"Hitte\": 5}`")
        
        tasks_input = st.text_area(
            "Plak hier de AI-gegenereerde JSON:",
            value=doc['ai_tasks_json'] or "",
            height=200,
            key="tasks_input"
        )
        
        if st.button("💾 Opslaan Opgave Analyse", type="primary", key="save_tasks"):
            if tasks_input.strip():
                # Validate JSON
                try:
                    parsed = json.loads(tasks_input.strip())
                    if isinstance(parsed, dict):
                        # Re-serialize to ensure clean JSON
                        clean_json = json.dumps(parsed, ensure_ascii=False, indent=2)
                        if save_ai_tasks(doc_id, clean_json):
                            st.success("Opgave analyse opgeslagen!")
                            st.rerun()
                        else:
                            st.error("Fout bij opslaan")
                    else:
                        st.error("JSON moet een object zijn (niet een array)")
                except json.JSONDecodeError as e:
                    st.error(f"Ongeldige JSON: {e}")
            else:
                st.warning("Voer eerst JSON in")


# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================
st.sidebar.title("🌍 Klimaatadaptatie KB")
page = st.sidebar.radio(
    "Navigatie",
    ["📚 Documenten", "🔤 Zoektermen", "📡 RSS Feeds", "💬 Prompt Manager", "▶️ Pipeline"]
)

# =============================================================================
# MAIN CONTENT
# =============================================================================

if page == "📚 Documenten":
    st.title("Documentbrowser")
    
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
        with st.expander("🎛️ Filters", expanded=False):
            col_source, col_status, col_pdf = st.columns(3)
            
            with col_source:
                all_sources = get_unique_sources()
                selected_sources = st.multiselect(
                    "📁 Bron",
                    options=all_sources,
                    default=[],
                    placeholder="Alle bronnen"
                )
            
            with col_status:
                status_filter = st.radio(
                    "📊 Status",
                    ["Alle", "new", "analyzed"],
                    horizontal=True
                )
            
            with col_pdf:
                pdf_filter = st.radio(
                    "📄 PDF",
                    ["Alle", "Met PDF", "Zonder PDF"],
                    horizontal=True
                )
            
            # Date range
            col_date1, col_date2, col_limit = st.columns(3)
            with col_date1:
                date_from = st.date_input(
                    "📅 Datum van",
                    value=None,
                    format="DD-MM-YYYY"
                )
            with col_date2:
                date_to = st.date_input(
                    "📅 Datum tot",
                    value=None,
                    format="DD-MM-YYYY"
                )
            with col_limit:
                limit = st.selectbox("Max resultaten", [50, 100, 200, 500], index=1)
        
        # ==========================================================================
        # VIEW SWITCHER
        # ==========================================================================
        view_mode = st.radio(
            "Weergave",
            ["📋 Lijst", "🃏 Kaarten"],
            horizontal=True,
            label_visibility="collapsed"
        )
        
        # Convert date inputs to datetime
        date_from_dt = datetime.combine(date_from, datetime.min.time()) if date_from else None
        date_to_dt = datetime.combine(date_to, datetime.max.time()) if date_to else None
        
        # Load documents with filters
        docs = load_documents_filtered(
            search_query=search_query,
            sources=selected_sources if selected_sources else None,
            status_filter=status_filter,
            has_pdf_filter=pdf_filter,
            date_from=date_from_dt,
            date_to=date_to_dt,
            limit=limit
        )
        
        if not docs:
            st.info("Geen documenten gevonden. Pas de filters aan of voer de pipeline uit.")
        else:
            st.caption(f"Toont **{len(docs)}** documenten • Klik op een rij om details te openen")
            
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
                    st.rerun()
            
            else:
                # --- CARD VIEW ---
                for doc in docs:
                    render_card(doc)


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
    st.title("RSS Feed Configuratie")
    
    feeds_path = os.path.join(config.BASE_DIR, "feeds.txt")
    feeds_content = load_file_content(feeds_path)
    
    # Show current stats
    feeds = config.load_feeds()
    st.info(f"Momenteel geconfigureerd: **{len(feeds)} feeds**")
    
    # Feed editor
    new_feeds = st.text_area(
        "Bewerk RSS Feeds (formaat: URL | Bronnaam)",
        feeds_content,
        height=500
    )
    
    if st.button("Opslaan Feeds"):
        if save_file_content(feeds_path, new_feeds):
            st.success("Feeds opgeslagen! Wijzigingen worden toegepast bij volgende pipeline run.")
    
    # Show feed list
    with st.expander("Bekijk Huidige Feeds"):
        for feed in feeds:
            st.write(f"- **{feed['source_name']}**: `{feed['url'][:60]}...`")


elif page == "💬 Prompt Manager":
    st.title("Prompt Manager")
    st.write("Beheer de AI prompts voor samenvatting en opgave analyse.")
    
    # Load current prompts
    prompts = config.load_prompts()
    
    st.subheader("📝 Samenvatting Prompt")
    st.caption("Template voor het genereren van document samenvattingen. De `{document_text}` placeholder is beschermd en kan niet worden verwijderd.")
    
    # Split summary prompt at {document_text}
    summary_template = prompts.get("summary_prompt", "")
    placeholder = "{document_text}"
    if placeholder in summary_template:
        summary_before, summary_after = summary_template.split(placeholder, 1)
    else:
        # If placeholder missing, add it at the end
        summary_before = summary_template
        summary_after = ""
    
    summary_before_edit = st.text_area(
        "Prompt voor de documenttekst:",
        value=summary_before,
        height=150,
        key="summary_before"
    )
    
    st.text_area(
        "Placeholder (alleen-lezen):",
        value=placeholder,
        height=50,
        disabled=True,
        key="summary_placeholder"
    )
    
    summary_after_edit = st.text_area(
        "Prompt na de documenttekst:",
        value=summary_after,
        height=150,
        key="summary_after"
    )
    
    # Reconstruct full prompt
    summary_prompt = summary_before_edit + placeholder + summary_after_edit
    
    st.subheader("📊 Relevantie/Opgave Prompt")
    st.caption("Template voor het analyseren van relevantie voor de 21 NAS opgaven. De `{document_text}` placeholder is beschermd en kan niet worden verwijderd.")
    
    # Split relevance prompt at {document_text}
    relevance_template = prompts.get("relevance_prompt", "")
    if placeholder in relevance_template:
        relevance_before, relevance_after = relevance_template.split(placeholder, 1)
    else:
        # If placeholder missing, add it at the end
        relevance_before = relevance_template
        relevance_after = ""
    
    relevance_before_edit = st.text_area(
        "Prompt voor de documenttekst:",
        value=relevance_before,
        height=200,
        key="relevance_before"
    )
    
    st.text_area(
        "Placeholder (alleen-lezen):",
        value=placeholder,
        height=50,
        disabled=True,
        key="relevance_placeholder"
    )
    
    relevance_after_edit = st.text_area(
        "Prompt na de documenttekst:",
        value=relevance_after,
        height=150,
        key="relevance_after"
    )
    
    # Reconstruct full prompt
    relevance_prompt = relevance_before_edit + placeholder + relevance_after_edit
    
    if st.button("💾 Opslaan Prompts", type="primary"):
        new_prompts = {
            "summary_prompt": summary_prompt,
            "relevance_prompt": relevance_prompt
        }
        if config.save_prompts(new_prompts):
            st.success("Prompts opgeslagen!")
        else:
            st.error("Fout bij opslaan prompts")
    
    # Preview section
    with st.expander("👁️ Prompt Preview"):
        st.write("Zo ziet de samenvatting prompt eruit met voorbeeld tekst:")
        preview = summary_prompt.replace("{document_text}", "[... DOCUMENT TEKST HIER ...]")
        st.code(preview[:500] + "..." if len(preview) > 500 else preview)


elif page == "▶️ Pipeline":
    st.title("Pipeline Uitvoeren")
    
    st.write("""
    Klik op de knop hieronder om de ingestie pipeline handmatig uit te voeren.
    Dit zal:
    1. Alle geconfigureerde RSS feeds ophalen
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
    col8.metric("Feeds", len(config.load_feeds()))
    
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

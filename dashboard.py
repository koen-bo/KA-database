"""
Climate Adaptation Knowledge Base - Dashboard

A simple Streamlit frontend to:
- Search and browse documents
- Edit zoektermen and feeds
- Access PDF files
- Run the ingestion pipeline

Run with: streamlit run dashboard.py
"""

import os
import subprocess
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import or_

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


def load_documents(search_query: str = "", limit: int = 100) -> pd.DataFrame:
    """Load documents from database with optional search."""
    with get_session() as session:
        query = session.query(Document)
        
        if search_query:
            search = f"%{search_query}%"
            query = query.filter(
                or_(
                    Document.title.ilike(search),
                    Document.full_text.ilike(search),
                    Document.source_name.ilike(search)
                )
            )
        
        docs = query.order_by(Document.fetched_at.desc()).limit(limit).all()
        
        data = []
        for doc in docs:
            data.append({
                "ID": doc.id,
                "Titel": doc.title[:80] + "..." if doc.title and len(doc.title) > 80 else doc.title,
                "Bron": doc.source_name,
                "Type": doc.content_type,
                "Datum": doc.publication_date.strftime("%Y-%m-%d") if doc.publication_date else "",
                "Status": doc.processing_status,
                "Heeft PDF": "Ja" if doc.local_file_path else "Nee",
                "URL": doc.url,
                "PDF Pad": doc.local_file_path or ""
            })
        
        return pd.DataFrame(data)


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
            }
    return None


# Sidebar navigation
st.sidebar.title("Navigatie")
page = st.sidebar.radio(
    "Ga naar",
    ["Documenten", "Zoektermen", "RSS Feeds", "Pipeline Uitvoeren"]
)

# Main content
st.title("Kennisbank Klimaatadaptatie")

if page == "Documenten":
    st.header("Documentbrowser")
    
    # Search box
    col1, col2 = st.columns([3, 1])
    with col1:
        search = st.text_input("Zoek documenten", placeholder="Voer zoektermen in...")
    with col2:
        limit = st.selectbox("Toon", [25, 50, 100, 200], index=1)
    
    # Load and display documents
    df = load_documents(search, limit)
    
    if df.empty:
        st.info("Geen documenten gevonden. Voer de pipeline uit om nieuwe documenten op te halen.")
    else:
        st.write(f"Toont {len(df)} documenten")
        
        # Display table
        st.dataframe(
            df[["ID", "Titel", "Bron", "Type", "Datum", "Status", "Heeft PDF"]],
            use_container_width=True,
            hide_index=True
        )
        
        # Document details
        st.subheader("Documentdetails")
        doc_id = st.number_input("Voer Document ID in om details te bekijken", min_value=1, step=1)
        
        if st.button("Bekijk Document"):
            doc = get_document_details(doc_id)
            if doc:
                st.write(f"**Titel:** {doc['title']}")
                st.write(f"**Bron:** {doc['source_name']}")
                st.write(f"**URL:** [{doc['url']}]({doc['url']})")
                st.write(f"**Type:** {doc['content_type']}")
                st.write(f"**Opgehaald:** {doc['fetched_at']}")
                
                if doc['local_file_path']:
                    st.write(f"**PDF:** `{doc['local_file_path']}`")
                    if os.path.exists(doc['local_file_path']):
                        with open(doc['local_file_path'], "rb") as f:
                            st.download_button(
                                "Download PDF",
                                f.read(),
                                file_name=os.path.basename(doc['local_file_path']),
                                mime="application/pdf"
                            )
                else:
                    # No PDF - offer to refetch
                    st.warning("Geen PDF gekoppeld aan dit document")
                    if st.button("🔍 Probeer PDF te vinden", key=f"refetch_{doc_id}"):
                        with st.spinner("Zoeken naar PDF op pagina..."):
                            fetcher = ContentFetcher()
                            result = fetcher.fetch(doc['url'], doc['source_name'] or "Onbekend", doc['title'] or "")
                            
                            if result and result["file_path"]:
                                # Update database
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
                
                with st.expander("Volledige Tekst Voorvertoning"):
                    st.text(doc['full_text'][:5000] if doc['full_text'] else "Geen tekst beschikbaar")
            else:
                st.error(f"Document {doc_id} niet gevonden")

elif page == "Zoektermen":
    st.header("Zoekterm Configuratie")
    
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
        
        if st.button("Sla Tier 1 Zoektermen op"):
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
        
        if st.button("Sla Tier 2 Zoektermen op"):
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
        
        if st.button("Sla Contextwoorden op"):
            if save_file_content(context_path, new_context):
                st.success("Contextwoorden opgeslagen!")

elif page == "RSS Feeds":
    st.header("RSS Feed Configuratie")
    
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
    
    if st.button("Sla Feeds op"):
        if save_file_content(feeds_path, new_feeds):
            st.success("Feeds opgeslagen! Wijzigingen worden toegepast bij volgende pipeline run.")
    
    # Show feed list
    with st.expander("Bekijk Huidige Feeds"):
        for feed in feeds:
            st.write(f"- **{feed['source_name']}**: `{feed['url'][:60]}...`")

elif page == "Pipeline Uitvoeren":
    st.header("Voer Ingestie Pipeline uit")
    
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
        docs_with_pdf = session.query(Document).filter(Document.local_file_path != None).count()
        docs_without_pdf = total_docs - docs_with_pdf
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Totaal Documenten", total_docs)
    col2.metric("Nieuw (Onverwerkt)", new_docs)
    col3.metric("Met PDF", docs_with_pdf)
    col4.metric("Geen PDF", docs_without_pdf)
    
    st.subheader("Acties")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("Voer Pipeline Nu Uit", type="primary"):
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
        if st.button("Herhaal Ontbrekende PDF's"):
            with st.spinner("Zoeken naar PDF's in bestaande documenten..."):
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
st.sidebar.markdown("**Klimaatadaptatie KB**")
st.sidebar.markdown(f"Database: `{config.DATABASE_PATH}`")

"""
Climate Adaptation Knowledge Base - Dashboard

A simple Streamlit frontend to:
- Search and browse documents
- Edit keywords and feeds
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
    page_title="Climate Adaptation KB",
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
                "Title": doc.title[:80] + "..." if doc.title and len(doc.title) > 80 else doc.title,
                "Source": doc.source_name,
                "Type": doc.content_type,
                "Date": doc.publication_date.strftime("%Y-%m-%d") if doc.publication_date else "",
                "Status": doc.processing_status,
                "Has PDF": "Yes" if doc.local_file_path else "No",
                "URL": doc.url,
                "PDF Path": doc.local_file_path or ""
            })
        
        return pd.DataFrame(data)


def load_file_content(filepath: str) -> str:
    """Load content from a text file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error loading file: {e}"


def save_file_content(filepath: str, content: str) -> bool:
    """Save content to a text file."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        st.error(f"Error saving: {e}")
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
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Go to",
    ["Documents", "Keywords", "RSS Feeds", "Run Pipeline"]
)

# Main content
st.title("Climate Adaptation Knowledge Base")

if page == "Documents":
    st.header("Document Browser")
    
    # Search box
    col1, col2 = st.columns([3, 1])
    with col1:
        search = st.text_input("Search documents", placeholder="Enter keywords...")
    with col2:
        limit = st.selectbox("Show", [25, 50, 100, 200], index=1)
    
    # Load and display documents
    df = load_documents(search, limit)
    
    if df.empty:
        st.info("No documents found. Run the pipeline to fetch new documents.")
    else:
        st.write(f"Showing {len(df)} documents")
        
        # Display table
        st.dataframe(
            df[["ID", "Title", "Source", "Type", "Date", "Status", "Has PDF"]],
            use_container_width=True,
            hide_index=True
        )
        
        # Document details
        st.subheader("Document Details")
        doc_id = st.number_input("Enter Document ID to view details", min_value=1, step=1)
        
        if st.button("View Document"):
            doc = get_document_details(doc_id)
            if doc:
                st.write(f"**Title:** {doc['title']}")
                st.write(f"**Source:** {doc['source_name']}")
                st.write(f"**URL:** [{doc['url']}]({doc['url']})")
                st.write(f"**Type:** {doc['content_type']}")
                st.write(f"**Fetched:** {doc['fetched_at']}")
                
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
                    st.warning("No PDF attached to this document")
                    if st.button("🔍 Try to Find PDF", key=f"refetch_{doc_id}"):
                        with st.spinner("Searching for PDF on page..."):
                            fetcher = ContentFetcher()
                            result = fetcher.fetch(doc['url'], doc['source_name'] or "Unknown", doc['title'] or "")
                            
                            if result and result["file_path"]:
                                # Update database
                                with get_session() as session:
                                    db_doc = session.query(Document).filter(Document.id == doc_id).first()
                                    if db_doc:
                                        db_doc.content_type = result["type"]
                                        db_doc.local_file_path = result["file_path"]
                                        db_doc.full_text = result["text"]
                                        session.commit()
                                
                                st.success(f"PDF found and saved: {result['file_path']}")
                                st.rerun()
                            else:
                                st.info("No PDF download link found on this page")
                
                with st.expander("Full Text Preview"):
                    st.text(doc['full_text'][:5000] if doc['full_text'] else "No text available")
            else:
                st.error(f"Document {doc_id} not found")

elif page == "Keywords":
    st.header("Keyword Configuration")
    
    tab1, tab2, tab3 = st.tabs(["Tier 1 Keywords", "Tier 2 Keywords", "Context Words"])
    
    with tab1:
        st.write("**Tier 1: Direct Hit Keywords** - Documents with these are always downloaded")
        tier1_path = os.path.join(config.BASE_DIR, "tier1_keywords.txt")
        tier1_content = load_file_content(tier1_path)
        
        new_tier1 = st.text_area(
            "Edit Tier 1 Keywords (one per line, # for comments)",
            tier1_content,
            height=400
        )
        
        if st.button("Save Tier 1 Keywords"):
            if save_file_content(tier1_path, new_tier1):
                st.success("Tier 1 keywords saved!")
    
    with tab2:
        st.write("**Tier 2: Context-Dependent Keywords** - Only downloaded with context words")
        tier2_path = os.path.join(config.BASE_DIR, "tier2_keywords.txt")
        tier2_content = load_file_content(tier2_path)
        
        new_tier2 = st.text_area(
            "Edit Tier 2 Keywords ([Theme] headers, one keyword per line)",
            tier2_content,
            height=400
        )
        
        if st.button("Save Tier 2 Keywords"):
            if save_file_content(tier2_path, new_tier2):
                st.success("Tier 2 keywords saved!")
    
    with tab3:
        st.write("**Context Words** - Make Tier 2 keywords relevant")
        context_path = os.path.join(config.BASE_DIR, "context_words.txt")
        context_content = load_file_content(context_path)
        
        new_context = st.text_area(
            "Edit Context Words (one per line)",
            context_content,
            height=300
        )
        
        if st.button("Save Context Words"):
            if save_file_content(context_path, new_context):
                st.success("Context words saved!")

elif page == "RSS Feeds":
    st.header("RSS Feed Configuration")
    
    feeds_path = os.path.join(config.BASE_DIR, "feeds.txt")
    feeds_content = load_file_content(feeds_path)
    
    # Show current stats
    feeds = config.load_feeds()
    st.info(f"Currently configured: **{len(feeds)} feeds**")
    
    # Feed editor
    new_feeds = st.text_area(
        "Edit RSS Feeds (format: URL | Source Name)",
        feeds_content,
        height=500
    )
    
    if st.button("Save Feeds"):
        if save_file_content(feeds_path, new_feeds):
            st.success("Feeds saved! Changes will apply on next pipeline run.")
    
    # Show feed list
    with st.expander("View Current Feeds"):
        for feed in feeds:
            st.write(f"- **{feed['source_name']}**: `{feed['url'][:60]}...`")

elif page == "Run Pipeline":
    st.header("Run Ingestion Pipeline")
    
    st.write("""
    Click the button below to run the ingestion pipeline manually.
    This will:
    1. Fetch all configured RSS feeds
    2. Filter by keywords
    3. Download relevant documents
    4. Store in database
    """)
    
    # Stats
    with get_session() as session:
        total_docs = session.query(Document).count()
        new_docs = session.query(Document).filter(Document.processing_status == "new").count()
        docs_with_pdf = session.query(Document).filter(Document.local_file_path != None).count()
        docs_without_pdf = total_docs - docs_with_pdf
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Documents", total_docs)
    col2.metric("New (Unprocessed)", new_docs)
    col3.metric("With PDF", docs_with_pdf)
    col4.metric("No PDF", docs_without_pdf)
    
    st.subheader("Actions")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("Run Pipeline Now", type="primary"):
            with st.spinner("Running pipeline..."):
                result = subprocess.run(
                    ["python", "main.py"],
                    capture_output=True,
                    text=True,
                    cwd=config.BASE_DIR
                )
                
                if result.returncode == 0:
                    st.success("Pipeline completed successfully!")
                    st.code(result.stdout)
                else:
                    st.error("Pipeline failed!")
                    st.code(result.stderr)
    
    with col_b:
        if st.button("Refetch Missing PDFs"):
            with st.spinner("Searching for PDFs in existing documents..."):
                result = subprocess.run(
                    ["python", "refetch_pdfs.py"],
                    capture_output=True,
                    text=True,
                    cwd=config.BASE_DIR
                )
                
                if result.returncode == 0:
                    st.success("PDF refetch completed!")
                    st.code(result.stdout)
                else:
                    st.error("PDF refetch failed!")
                    st.code(result.stderr)

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**Climate Adaptation KB**")
st.sidebar.markdown(f"Database: `{config.DATABASE_PATH}`")

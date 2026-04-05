"""
Climate Adaptation Knowledge Base - Database Module

SQLAlchemy 2.0+ ORM model for the documents table.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, String, Text, Boolean, DateTime, Integer, event, text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

import config


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


class Document(Base):
    """
    Document model representing a policy document in the knowledge base.
    
    Stores both the source metadata (from RSS) and AI analysis results.
    """
    __tablename__ = "documents"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Source metadata
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discovery_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    discovery_source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Fetching metadata
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 'pdf' or 'html'
    local_file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)  # Path to stored PDF
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    
    # Content
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cleaned_text_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cleaned_text_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    screening_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    screening_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    screened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    screening_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    screening_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    screening_input_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_output_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_exploratory_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    screening_exploratory_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    screening_exploratory_screened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    screening_exploratory_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    screening_exploratory_input_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_exploratory_output_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screening_exploratory_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Processing status
    processing_status: Mapped[str] = mapped_column(String(50), default="new")  # 'new', 'analyzed', 'failed'
    keyword_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array string
    
    # AI Analysis results
    is_relevant: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_tasks_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string with 21 task scores
    
    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title[:50] if self.title else 'N/A'}...')>"


# Engine singleton
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        database_url = f"sqlite:///{config.DATABASE_PATH}"
        _engine = create_engine(database_url, echo=False)

        # Apply SQLite PRAGMAs on every new DB-API connection.
        if database_url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.close()
    return _engine


def get_session() -> Session:
    """Create a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db() -> None:
    """Initialize the database by creating all tables."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    _ensure_schema_columns()
    print("SQLite PRAGMAs enabled: journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON")
    print(f"Database initialized: {config.DATABASE_PATH}")


def _ensure_schema_columns() -> None:
    """Idempotent schema migration for newly introduced columns."""
    engine = get_engine()
    with engine.begin() as conn:
        existing_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(documents);")).fetchall()
        }
        if "discovery_method" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN discovery_method TEXT;"))
        if "discovery_source_url" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN discovery_source_url TEXT;"))
        if "doc_type" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN doc_type TEXT;"))
        if "keyword_tags" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN keyword_tags TEXT;"))
        if "thumbnail_url" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN thumbnail_url TEXT;"))
        if "cleaned_text" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN cleaned_text TEXT;"))
        if "cleaned_text_updated_at" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN cleaned_text_updated_at DATETIME;"))
        if "cleaned_text_version" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN cleaned_text_version TEXT;"))
        if "screening_status" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_status TEXT;"))
        if "screening_requested_at" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_requested_at DATETIME;"))
        if "screened_at" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screened_at DATETIME;"))
        if "screening_model" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_model TEXT;"))
        if "screening_version" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_version TEXT;"))
        if "screening_input_json" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_input_json TEXT;"))
        if "screening_output_json" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_output_json TEXT;"))
        if "screening_context_json" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_context_json TEXT;"))
        if "screening_error" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_error TEXT;"))
        if "screening_exploratory_status" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_status TEXT;"))
        if "screening_exploratory_requested_at" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_requested_at DATETIME;"))
        if "screening_exploratory_screened_at" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_screened_at DATETIME;"))
        if "screening_exploratory_model" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_model TEXT;"))
        if "screening_exploratory_input_json" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_input_json TEXT;"))
        if "screening_exploratory_output_json" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_output_json TEXT;"))
        if "screening_exploratory_error" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN screening_exploratory_error TEXT;"))


def url_exists(url: str) -> bool:
    """Check if a URL already exists in the database."""
    with get_session() as session:
        result = session.query(Document).filter(Document.url == url).first()
        return result is not None


def add_document(
    url: str,
    source_name: str,
    title: str,
    publication_date: Optional[datetime] = None,
    content_type: Optional[str] = None,
    local_file_path: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    full_text: Optional[str] = None,
    processing_status: str = "new",
    discovery_method: Optional[str] = None,
    discovery_source_url: Optional[str] = None,
    doc_type: Optional[str] = None,
    keyword_tags: Optional[str] = None,
) -> Document:
    """
    Add a new document to the database.
    
    Args:
        url: The direct link to the document
        source_name: Source name (e.g., "Tweede Kamer")
        title: Document title from RSS
        publication_date: Publication date from RSS
        content_type: 'pdf' or 'html'
        local_file_path: Path to locally stored PDF file
        full_text: Extracted text content
        processing_status: Initial status (default: 'new')
    
    Returns:
        The created Document object
    """
    with get_session() as session:
        doc = Document(
            url=url,
            source_name=source_name,
            title=title,
            publication_date=publication_date,
            discovery_method=discovery_method,
            discovery_source_url=discovery_source_url,
            doc_type=doc_type,
            fetched_at=datetime.now(),
            content_type=content_type,
            local_file_path=local_file_path,
            thumbnail_url=thumbnail_url,
            full_text=full_text,
            processing_status=processing_status,
            keyword_tags=keyword_tags,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc


def update_document_tags(doc_id: int, keyword_tags_json: str) -> bool:
    """Update keyword tags for a single document. Returns True when updated."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        doc.keyword_tags = keyword_tags_json
        session.commit()
        return True


def update_document_cleaned_text(doc_id: int, cleaned_text: str, version: str) -> bool:
    """Update cleaned text fields for a single document. Returns True when updated."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        doc.cleaned_text = cleaned_text
        doc.cleaned_text_updated_at = datetime.now()
        doc.cleaned_text_version = version
        session.commit()
        return True


def iter_documents_for_tag_backfill(
    since_id: int = 0,
    limit: Optional[int] = None,
    batch_size: int = 200,
):
    """
    Yield documents in deterministic ID order for tag backfill.
    """
    emitted = 0
    with get_session() as session:
        query = (
            session.query(Document)
            .filter(Document.id > since_id)
            .order_by(Document.id.asc())
        )
        if limit is not None and limit >= 0:
            query = query.limit(limit)

        if batch_size <= 0:
            batch_size = 200

        for doc in query.yield_per(batch_size):
            yield doc
            emitted += 1
            if limit is not None and limit >= 0 and emitted >= limit:
                break


def iter_documents_for_cleaned_text_backfill(
    since_id: int = 0,
    limit: Optional[int] = None,
    batch_size: int = 200,
):
    """
    Yield documents in deterministic ID order for cleaned text backfill.
    """
    emitted = 0
    with get_session() as session:
        query = (
            session.query(Document)
            .filter(Document.id > since_id)
            .order_by(Document.id.asc())
        )
        if limit is not None and limit >= 0:
            query = query.limit(limit)

        if batch_size <= 0:
            batch_size = 200

        for doc in query.yield_per(batch_size):
            yield doc
            emitted += 1
            if limit is not None and limit >= 0 and emitted >= limit:
                break


def iter_documents_for_screening(
    since_id: int = 0,
    limit: Optional[int] = None,
    batch_size: int = 200,
    retry_failed: bool = False,
    force_rescreen: bool = False,
    doc_id: Optional[int] = None,
):
    """
    Yield documents eligible for screening in deterministic ID order.
    """
    emitted = 0
    with get_session() as session:
        query = session.query(Document)

        if doc_id is not None:
            query = query.filter(Document.id == doc_id)
        else:
            query = query.filter(Document.id > since_id)

        if not force_rescreen:
            if retry_failed:
                query = query.filter(
                    (Document.screening_status == None)
                    | (Document.screening_status == "failed")
                )
            else:
                query = query.filter(Document.screening_status == None)

        query = query.order_by(Document.id.asc())

        if limit is not None and limit >= 0:
            query = query.limit(limit)

        if batch_size <= 0:
            batch_size = 200

        for doc in query.yield_per(batch_size):
            yield doc
            emitted += 1
            if limit is not None and limit >= 0 and emitted >= limit:
                break


def get_documents_by_status(status: str) -> list[Document]:
    """Get all documents with a specific processing status."""
    with get_session() as session:
        return session.query(Document).filter(Document.processing_status == status).all()


def mark_document_screening_pending(
    doc_id: int,
    input_json: str,
    model: str,
    screening_version: Optional[str] = None,
    context_json: Optional[str] = None,
) -> bool:
    """Mark a document as pending screening and persist the request payload."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_status = "pending"
        doc.screening_requested_at = now
        doc.screening_model = model
        doc.screening_version = screening_version or doc.screening_version
        doc.screening_input_json = input_json
        doc.screening_output_json = None
        doc.screened_at = None
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_error = None
        session.commit()
        return True


def mark_document_screening_completed(
    doc_id: int,
    input_json: str,
    output_json: str,
    model: str,
    screening_version: Optional[str] = None,
    context_json: Optional[str] = None,
) -> bool:
    """Persist a completed screening result."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_status = "completed"
        doc.screening_requested_at = doc.screening_requested_at or now
        doc.screened_at = now
        doc.screening_model = model
        doc.screening_version = screening_version or doc.screening_version
        doc.screening_input_json = input_json
        doc.screening_output_json = output_json
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_error = None
        session.commit()
        return True


def mark_document_screening_failed(
    doc_id: int,
    input_json: str,
    model: str,
    error_text: str,
    screening_version: Optional[str] = None,
    context_json: Optional[str] = None,
) -> bool:
    """Persist a failed screening attempt."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_status = "failed"
        doc.screening_requested_at = doc.screening_requested_at or now
        doc.screened_at = None
        doc.screening_model = model
        doc.screening_version = screening_version or doc.screening_version
        doc.screening_input_json = input_json
        doc.screening_output_json = None
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_error = error_text[:1000]
        session.commit()
        return True


def mark_document_exploratory_pending(
    doc_id: int,
    input_json: str,
    model: str,
    context_json: Optional[str] = None,
) -> bool:
    """Mark a document as pending exploratory screening."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_exploratory_status = "pending"
        doc.screening_exploratory_requested_at = now
        doc.screening_exploratory_model = model
        doc.screening_exploratory_input_json = input_json
        doc.screening_exploratory_output_json = None
        doc.screening_exploratory_screened_at = None
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_exploratory_error = None
        session.commit()
        return True


def mark_document_exploratory_completed(
    doc_id: int,
    input_json: str,
    output_json: str,
    model: str,
    context_json: Optional[str] = None,
) -> bool:
    """Persist a completed exploratory screening result."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_exploratory_status = "completed"
        doc.screening_exploratory_requested_at = doc.screening_exploratory_requested_at or now
        doc.screening_exploratory_screened_at = now
        doc.screening_exploratory_model = model
        doc.screening_exploratory_input_json = input_json
        doc.screening_exploratory_output_json = output_json
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_exploratory_error = None
        session.commit()
        return True


def mark_document_exploratory_failed(
    doc_id: int,
    input_json: str,
    model: str,
    error_text: str,
    context_json: Optional[str] = None,
) -> bool:
    """Persist a failed exploratory screening attempt while keeping factual output intact."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        now = datetime.now()
        doc.screening_exploratory_status = "failed"
        doc.screening_exploratory_requested_at = doc.screening_exploratory_requested_at or now
        doc.screening_exploratory_screened_at = None
        doc.screening_exploratory_model = model
        doc.screening_exploratory_input_json = input_json
        doc.screening_exploratory_output_json = None
        doc.screening_context_json = context_json or doc.screening_context_json
        doc.screening_exploratory_error = error_text[:1000]
        session.commit()
        return True


def get_latest_source_timestamp(source_name: str) -> Optional[datetime]:
    """
    Return latest known timestamp for a source.

    Uses max(publication_date) and max(fetched_at), then returns the newest of both.
    """
    with get_session() as session:
        max_pub = (
            session.query(func.max(Document.publication_date))
            .filter(Document.source_name == source_name)
            .scalar()
        )
        max_fetch = (
            session.query(func.max(Document.fetched_at))
            .filter(Document.source_name == source_name)
            .scalar()
        )

    if max_pub and max_fetch:
        return max_pub if max_pub >= max_fetch else max_fetch
    return max_pub or max_fetch


def update_document_analysis(
    doc_id: int,
    is_relevant: bool,
    ai_summary: str,
    ai_tasks_json: str
) -> None:
    """Update a document with AI analysis results."""
    with get_session() as session:
        doc = session.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.is_relevant = is_relevant
            doc.ai_summary = ai_summary
            doc.ai_tasks_json = ai_tasks_json
            doc.processing_status = "analyzed"
            session.commit()

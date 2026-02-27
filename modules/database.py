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
    
    # Fetching metadata
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 'pdf' or 'html'
    local_file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)  # Path to stored PDF
    
    # Content
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
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
        if "keyword_tags" not in existing_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN keyword_tags TEXT;"))


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
    full_text: Optional[str] = None,
    processing_status: str = "new",
    discovery_method: Optional[str] = None,
    discovery_source_url: Optional[str] = None,
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
            fetched_at=datetime.now(),
            content_type=content_type,
            local_file_path=local_file_path,
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


def get_documents_by_status(status: str) -> list[Document]:
    """Get all documents with a specific processing status."""
    with get_session() as session:
        return session.query(Document).filter(Document.processing_status == status).all()


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

"""
Climate Adaptation Knowledge Base - Database Module

SQLAlchemy 2.0+ ORM model for the documents table.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, String, Text, Boolean, DateTime, Integer
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
    
    # Fetching metadata
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 'pdf' or 'html'
    local_file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)  # Path to stored PDF
    
    # Content
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Processing status
    processing_status: Mapped[str] = mapped_column(String(50), default="new")  # 'new', 'analyzed', 'failed'
    
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
    print(f"Database initialized: {config.DATABASE_PATH}")


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
    processing_status: str = "new"
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
            fetched_at=datetime.now(),
            content_type=content_type,
            local_file_path=local_file_path,
            full_text=full_text,
            processing_status=processing_status
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc


def get_documents_by_status(status: str) -> list[Document]:
    """Get all documents with a specific processing status."""
    with get_session() as session:
        return session.query(Document).filter(Document.processing_status == status).all()


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

from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class FetchedPage(SQLModel, table=True):
    """
    SQLModel representing a fetched and extracted web page.
    Stores extracted content alongside metadata for deduplication
    and quality assessment.
    """
    __tablename__ = "fetched_pages"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    search_result_id: UUID = Field(
        foreign_key="search_results.id",
        index=True,
        nullable=False
    )
    url: str = Field(nullable=False)
    canonical_url: Optional[str] = Field(default=None, nullable=True)
    title: Optional[str] = Field(default=None, nullable=True)
    content: str = Field(default="", nullable=False)
    content_hash: str = Field(nullable=False, index=True)
    content_length: int = Field(default=0, nullable=False)
    raw_html_path: Optional[str] = Field(default=None, nullable=True)
    extraction_quality_score: float = Field(default=0.0, nullable=False)
    fetch_status: str = Field(default="pending", nullable=False)
    error_message: Optional[str] = Field(default=None, nullable=True)
    metadata_: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


# --- DTO schemas ---

class FetchRequest(SQLModel):
    """
    Request payload to trigger page fetching for a completed research session.
    """
    session_id: UUID


class FetchedPageRead(SQLModel):
    """
    Response DTO for a single fetched page.
    """
    url: str
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    content_preview: str
    content_hash: str
    content_length: int
    extraction_quality_score: float
    fetch_status: str
    error_message: Optional[str] = None


class FetchResponse(SQLModel):
    """
    Response payload wrapping all fetched pages for a session.
    """
    session_id: UUID
    total_pages: int
    successful: int
    failed: int
    pages: List[FetchedPageRead]

from datetime import datetime
from uuid import UUID
from typing import List, Optional

from sqlmodel import SQLModel, Field


class ResearchSourceRead(SQLModel):
    """
    Read model for a source used during research.
    """
    page_id: UUID
    search_result_id: UUID
    title: str
    url: str
    domain: str
    source_type: str
    status: str
    analysis_status: str
    quality_score: float
    credibility_score: float
    fetch_duration_ms: Optional[float] = None
    analysis_duration_ms: Optional[float] = None
    word_count: int = 0
    token_count: int = 0
    extraction_quality_score: float = 0.0
    summary: Optional[str] = None
    key_claims: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)
    research_relevance: str = "Unknown"
    created_at: datetime


class ResearchSourcesResponse(SQLModel):
    """
    Response model for all sources used in a session.
    """
    session_id: UUID
    sources: List[ResearchSourceRead] = Field(default_factory=list)
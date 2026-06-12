from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional
from sqlmodel import SQLModel, Field


class SearchResult(SQLModel, table=True):
    """
    SQLModel representing a stored Search Result returned from SearXNG.
    """
    __tablename__ = "search_results"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    query_id: UUID = Field(
        foreign_key="generated_queries.id",
        index=True,
        nullable=False
    )
    title: str = Field(nullable=False)
    url: str = Field(nullable=False)
    snippet: str = Field(nullable=False)
    engine: str = Field(nullable=False)
    score: float = Field(nullable=False, default=1.0)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False
    )


# --- DTO schemas ---

class SearchRequest(SQLModel):
    """
    Request payload containing the research question to search queries for.
    """
    question: str


class SearchResultRead(SQLModel):
    """
    Response DTO containing search result properties.
    """
    title: str
    url: str
    snippet: str
    engine: str
    score: float


class SearchResponse(SQLModel):
    """
    Response payload containing the generated queries and deduplicated search results.
    """
    queries: List[str]
    results: List[SearchResultRead]

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


class SearchCandidate(SQLModel):
    """
    Represents a potential page to fetch, gathered from a Connector.
    Includes provenance to track where the candidate came from.
    """
    url: str
    title: str
    snippet: str
    source: str           # e.g. "searxng", "arxiv", "local_memory"
    connector: str        # e.g. "SearXNGConnector"
    generated_query: str  # The exact query string that produced this candidate
    scores: dict = Field(default_factory=dict) # e.g. {"retrieval": 0.8, "credibility": 0.9}
    final_score: float = Field(default=0.0)
    metadata: dict = Field(default_factory=dict)


class CandidatePool(SQLModel):
    """
    Holds the aggregated pool of search candidates retrieved from all connectors,
    along with telemetry and statistics for the retrieval phase.
    """
    candidates: List[SearchCandidate] = Field(default_factory=list)
    connector_metrics: dict = Field(default_factory=dict) # e.g. {"searxng": 50, "arxiv": 12}
    duplicates_removed: int = Field(default=0)
    duplicate_domains: dict = Field(default_factory=dict) # Count of dropped candidates by domain
    average_credibility: float = Field(default=0.0)
    average_freshness: float = Field(default=0.0)
    average_rank: float = Field(default=0.0)


class RetrievalDecision(SQLModel):
    """
    Records why a candidate was accepted or rejected during the ranking and fetching pipeline.
    """
    url: str
    connector: str
    retrieval_score: float = 0.0
    credibility_score: float = 0.0
    freshness_score: float = 0.0
    diversity_score: float = 0.0
    citation_score: float = 0.0
    cross_encoder_score: Optional[float] = None
    final_score: float = 0.0
    accepted: bool = False
    rejection_reason: Optional[str] = None


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

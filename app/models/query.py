from datetime import datetime
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class GeneratedQuery(SQLModel, table=True):
    """
    SQLModel representing a generated search query linked to a Research Session.
    """
    __tablename__ = "generated_queries"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False
    )
    query_text: str = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


from pydantic import BaseModel, Field
from typing import List
from enum import Enum

class QueryIntent(str, Enum):
    SURVEY = "survey"
    PAPER = "paper"
    IMPLEMENTATION = "implementation"
    BENCHMARK = "benchmark"
    DATASET = "dataset"
    COMPARISON = "comparison"
    NEWS = "news"
    BLOG = "blog"
    OPEN_PROBLEM = "open_problem"
    HISTORICAL = "historical"

class ResearchIntentPlan(BaseModel):
    """
    Structured query intelligence plan generated before issuing search queries.
    """
    entities: List[str] = Field(default_factory=list, description="Core entities extracted from the question")
    timeframe: str = Field(default="unknown", description="Relevant timeframe for the research")
    intents: List[QueryIntent] = Field(default_factory=list, description="Targeted search intents")
    queries: List[str] = Field(default_factory=list, description="Generated search queries covering the intents")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Planner confidence in its understanding of the question")

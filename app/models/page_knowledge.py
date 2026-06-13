from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class PageKnowledge(SQLModel, table=True):
    """
    SQLModel entity representing the page-level knowledge extracted
    from a fetched page, including summary, key points, main topics,
    entities, and importance score.
    """
    __tablename__ = "page_knowledges"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    page_id: UUID = Field(
        foreign_key="fetched_pages.id",
        index=True,
        nullable=False
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False
    )
    summary: str = Field(nullable=False)
    key_points: str = Field(nullable=False) # JSON serialized string
    main_topics: str = Field(nullable=False) # JSON serialized string
    entities: str = Field(nullable=False) # JSON serialized string
    importance_score: float = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class PageAnalysisRequest(SQLModel):
    """
    Request DTO payload to trigger page analysis for a session.
    """
    session_id: UUID


class PageKnowledgeRead(SQLModel):
    """
    Response DTO containing properties of page knowledge with deserialized list fields.
    """
    id: UUID
    page_id: UUID
    session_id: UUID
    summary: str
    key_points: List[str]
    main_topics: List[str]
    entities: List[str]
    importance_score: float
    created_at: datetime


class PageAnalysisResponse(SQLModel):
    """
    Response DTO containing the list of analyzed page knowledges.
    """
    knowledges: List[PageKnowledgeRead]

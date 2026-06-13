from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class ResearchStrategyMemory(SQLModel, table=True):
    """
    SQLModel entity representing strategy lessons learned from past sessions of specific question types.
    SQLite doesn't natively support array types, so lists are stored as JSON serialized strings.
    """
    __tablename__ = "research_strategy_memories"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    question_type: str = Field(nullable=False, index=True)
    successful_queries: str = Field(nullable=False)  # JSON serialized list of strings
    successful_domains: str = Field(nullable=False)  # JSON serialized list of strings
    research_outcomes: str = Field(nullable=False)    # JSON serialized dict
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class StrategyLearnRequest(SQLModel):
    """
    Request DTO payload to trigger strategy learning from a completed session.
    """
    session_id: UUID


class StrategyConsultRequest(SQLModel):
    """
    Request DTO payload to consult strategy memory for a new question.
    """
    question: str


class StrategyMemoryRead(SQLModel):
    """
    Response DTO containing properties of a strategy memory with deserialized fields.
    """
    id: UUID
    question_type: str
    successful_queries: List[str]
    successful_domains: List[str]
    research_outcomes: dict
    created_at: datetime


class StrategyAdaptationResponse(SQLModel):
    """
    Response DTO outlining adaptation parameters for future queries.
    """
    question_type: str
    adapted_instructions: str
    successful_queries: List[str]
    successful_domains: List[str]

from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class GapPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResearchGap(SQLModel, table=True):
    """
    SQLModel entity representing an identified knowledge gap in the research session.
    """
    __tablename__ = "research_gaps"

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
    topic: str = Field(nullable=False, index=True)
    reason: str = Field(nullable=False)
    priority: GapPriority = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class GapDiscoveryRequest(SQLModel):
    """
    Request DTO payload to trigger gap discovery for a session.
    """
    session_id: UUID


class GapRead(SQLModel):
    """
    Response DTO containing properties of a research gap.
    """
    id: UUID
    session_id: UUID
    topic: str
    reason: str
    priority: GapPriority
    created_at: datetime


class GapDiscoveryResponse(SQLModel):
    """
    Response DTO containing the discovery result summary and persisted gaps.
    """
    known_topics: List[str]
    missing_topics: List[str]
    confidence: float
    gaps: List[GapRead]

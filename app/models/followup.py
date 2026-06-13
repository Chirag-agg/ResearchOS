from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class FollowupPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FollowupQuery(SQLModel, table=True):
    """
    SQLModel entity representing a planned search query, the reason for generating it,
    and its priority based on research gaps.
    """
    __tablename__ = "followup_queries"

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
    query: str = Field(nullable=False)
    reason: str = Field(nullable=False)
    priority: FollowupPriority = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class FollowupPlanningRequest(SQLModel):
    """
    Request DTO payload to trigger followup query generation.
    """
    session_id: UUID


class FollowupQueryRead(SQLModel):
    """
    Response DTO containing properties of a generated followup query.
    """
    id: UUID
    session_id: UUID
    query: str
    reason: str
    priority: FollowupPriority
    created_at: datetime


class FollowupPlanningResponse(SQLModel):
    """
    Response DTO wrapping the constructed followup query list.
    """
    queries: List[FollowupQueryRead]

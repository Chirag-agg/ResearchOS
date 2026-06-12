from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchSession(SQLModel, table=True):
    """
    SQLModel representing a Research Session persistence table.
    """
    __tablename__ = "research_sessions"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    question: str = Field(nullable=False)
    status: SessionStatus = Field(
        default=SessionStatus.PENDING,
        nullable=False
    )
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )
    updated_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


# --- DTO schemas ---

class SessionCreate(SQLModel):
    """
    Request model for creating a research session.
    """
    question: str


class SessionRead(SQLModel):
    """
    Response model for reading a research session.
    """
    id: UUID
    question: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime

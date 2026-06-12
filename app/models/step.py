from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class StepType(str, Enum):
    """
    Enum representing the type of step in the research pipeline.
    Even though only QUERY_GENERATION, SEARCH, and FETCH are active now,
    defining the full enum upfront enables a clean Replay Timeline later
    without reverse-engineering history from scattered tables.
    """
    QUERY_GENERATION = "query_generation"
    SEARCH = "search"
    FETCH = "fetch"
    CLAIM_EXTRACTION = "claim_extraction"


class StepStatus(str, Enum):
    """
    Execution status of an individual research step.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResearchStep(SQLModel, table=True):
    """
    SQLModel representing an individual step in the research pipeline.
    Enables future replay and audit trail by recording when each step
    started, finished, and what it produced.

    Example timeline for a session:
        Session
         ├── Step: query_generation (completed)
         ├── Step: search           (completed)
         ├── Step: fetch            (completed)
         └── Step: claim_extraction (pending)
    """
    __tablename__ = "research_steps"

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
    step_type: StepType = Field(nullable=False)
    status: StepStatus = Field(
        default=StepStatus.PENDING,
        nullable=False
    )
    input_data: Optional[str] = Field(default=None, nullable=True)
    output_summary: Optional[str] = Field(default=None, nullable=True)
    error_message: Optional[str] = Field(default=None, nullable=True)
    items_processed: int = Field(default=0, nullable=False)
    started_at: Optional[datetime] = Field(default=None, nullable=True)
    completed_at: Optional[datetime] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )

from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List, Optional
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class EventType(str, Enum):
    """
    Enum representing all possible research pipeline events.
    Every meaningful state transition in the research process has
    a corresponding event type for full observability.
    """
    SESSION_CREATED = "session_created"

    QUERY_GENERATION_STARTED = "query_generation_started"
    QUERY_GENERATION_COMPLETED = "query_generation_completed"

    SEARCH_STARTED = "search_started"
    SEARCH_COMPLETED = "search_completed"

    FETCH_STARTED = "fetch_started"
    FETCH_COMPLETED = "fetch_completed"

    CLAIM_EXTRACTION_STARTED = "claim_extraction_started"
    CLAIM_EXTRACTED = "claim_extracted"
    CLAIM_VALIDATED = "claim_validated"
    CLAIM_EXTRACTION_COMPLETED = "claim_extraction_completed"
    CLAIM_EXTRACTION_FAILED = "claim_extraction_failed"

    VALIDATION_STARTED = "validation_started"
    VALIDATION_COMPLETED = "validation_completed"
    VALIDATION_FAILED = "validation_failed"

    RESEARCH_STARTED = "research_started"
    RESEARCH_COMPLETED = "research_completed"
    RESEARCH_FAILED = "research_failed"

    PAGE_ANALYSIS_STARTED = "page_analysis_started"
    PAGE_ANALYZED = "page_analyzed"
    PAGE_ANALYSIS_COMPLETED = "page_analysis_completed"
    PAGE_ANALYSIS_FAILED = "page_analysis_failed"

    KNOWLEDGE_BUILD_STARTED = "knowledge_build_started"
    KNOWLEDGE_NODE_CREATED = "knowledge_node_created"
    KNOWLEDGE_BUILD_COMPLETED = "knowledge_build_completed"
    KNOWLEDGE_BUILD_FAILED = "knowledge_build_failed"

    GAP_DISCOVERY_STARTED = "gap_discovery_started"
    GAP_FOUND = "gap_found"
    GAP_DISCOVERY_COMPLETED = "gap_discovery_completed"
    GAP_DISCOVERY_FAILED = "gap_discovery_failed"

    FOLLOWUP_PLANNING_STARTED = "followup_planning_started"
    FOLLOWUP_QUERY_GENERATED = "followup_query_generated"
    FOLLOWUP_PLANNING_COMPLETED = "followup_planning_completed"
    FOLLOWUP_PLANNING_FAILED = "followup_planning_failed"

    RESEARCH_ROUND_STARTED = "research_round_started"
    RESEARCH_ROUND_COMPLETED = "research_round_completed"
    RESEARCH_STOPPED = "research_stopped"

    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"


class ResearchEvent(SQLModel, table=True):
    """
    SQLModel representing a single event in the research pipeline.
    Every publish() call produces one of these rows — forming a complete,
    chronological audit trail for any research session.
    """
    __tablename__ = "research_events"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False,
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False,
    )
    step_id: Optional[UUID] = Field(
        default=None,
        foreign_key="research_steps.id",
        nullable=True,
    )
    event_type: EventType = Field(nullable=False, index=True)
    payload_json: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False,
    )


# --- DTO schemas ---

class EventRead(SQLModel):
    """
    Response DTO for a single research event.
    """
    id: UUID
    session_id: UUID
    step_id: Optional[UUID] = None
    event_type: EventType
    payload: Optional[dict] = None
    timestamp: datetime


class EventListResponse(SQLModel):
    """
    Response payload wrapping a chronological list of events for a session.
    """
    session_id: UUID
    total_events: int
    events: List[EventRead]

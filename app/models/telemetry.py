from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List, Optional
from sqlmodel import SQLModel, Field
from pydantic import BaseModel
from app.models.base import get_utc_now


class TelemetryStage(str, Enum):
    """
    Enum representing pipeline stages for telemetry instrumentation.
    """
    SESSION = "session"
    QUERY_GENERATION = "query_generation"
    SEARCH = "search"
    FETCH = "fetch"
    PAGE_ANALYSIS = "page_analysis"
    CLAIM_EXTRACTION = "claim_extraction"
    VALIDATION = "validation"
    KNOWLEDGE_BUILDING = "knowledge_building"
    GAP_DISCOVERY = "gap_discovery"
    PLANNING = "planning"
    REPORT_GENERATION = "report_generation"


class TelemetryEventType(str, Enum):
    """
    Enum representing the type of telemetry event.
    """
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    PROGRESS = "progress"
    TOKEN_USAGE = "token_usage"
    METRIC = "metric"

    # URL lifecycle events
    URL_QUEUED = "url_queued"
    URL_FETCH_STARTED = "url_fetch_started"
    URL_FETCH_COMPLETED = "url_fetch_completed"
    URL_EXTRACTION_STARTED = "url_extraction_started"
    URL_EXTRACTION_COMPLETED = "url_extraction_completed"
    URL_ANALYSIS_STARTED = "url_analysis_started"
    URL_ANALYSIS_COMPLETED = "url_analysis_completed"

    # Chunk lifecycle events
    CHUNK_PROCESSING_STARTED = "chunk_processing_started"
    CHUNK_PROCESSING_COMPLETED = "chunk_processing_completed"

    # LLM call events
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"


class TelemetryEvent(SQLModel, table=True):
    """
    SQLModel representing a single telemetry event in the research pipeline.
    Provides ultra-granular visibility into every step of the system.
    """
    __tablename__ = "telemetry_events"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False,
    )
    session_id: UUID = Field(
        index=True,
        nullable=False,
    )
    timestamp: datetime = Field(
        default_factory=get_utc_now,
        nullable=False,
    )
    stage: TelemetryStage = Field(nullable=False, index=True)
    event_type: TelemetryEventType = Field(nullable=False, index=True)
    message: Optional[str] = Field(default=None, nullable=True)
    duration_ms: Optional[float] = Field(default=None, nullable=True)

    # Token tracking (native Ollama values)
    tokens_input: Optional[int] = Field(default=None, nullable=True)
    tokens_output: Optional[int] = Field(default=None, nullable=True)

    # Context identifiers
    url: Optional[str] = Field(default=None, nullable=True)
    page_id: Optional[str] = Field(default=None, nullable=True)
    query_id: Optional[str] = Field(default=None, nullable=True)
    claim_id: Optional[str] = Field(default=None, nullable=True)
    llm_call_id: Optional[str] = Field(default=None, nullable=True)

    # Research round tracking
    research_round: Optional[int] = Field(default=None, nullable=True)

    # Arbitrary metadata blob
    metadata_json: Optional[str] = Field(default=None, nullable=True)

    # System resource tracking via psutil
    cpu_percent: Optional[float] = Field(default=None, nullable=True)
    memory_mb: Optional[float] = Field(default=None, nullable=True)


# --- DTO Schemas ---

class TelemetryEventRead(BaseModel):
    """Response DTO for a single telemetry event."""
    id: UUID
    session_id: UUID
    timestamp: datetime
    stage: TelemetryStage
    event_type: TelemetryEventType
    message: Optional[str] = None
    duration_ms: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    url: Optional[str] = None
    page_id: Optional[str] = None
    query_id: Optional[str] = None
    claim_id: Optional[str] = None
    llm_call_id: Optional[str] = None
    research_round: Optional[int] = None
    metadata_json: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None


class ResearchMetrics(BaseModel):
    """Aggregated metrics for a research session, computed from telemetry events."""
    session_id: UUID
    question: str = ""
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_duration_ms: float = 0.0

    # Per-stage durations (sum of all COMPLETED events with duration_ms)
    query_generation_duration_ms: float = 0.0
    search_duration_ms: float = 0.0
    fetch_duration_ms: float = 0.0
    page_analysis_duration_ms: float = 0.0
    claim_extraction_duration_ms: float = 0.0
    validation_duration_ms: float = 0.0
    knowledge_duration_ms: float = 0.0
    report_duration_ms: float = 0.0

    # Page counts
    total_pages: int = 0
    processed_pages: int = 0
    failed_pages: int = 0

    # Claim counts
    total_claims: int = 0
    validated_claims: int = 0

    # LLM usage
    llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Efficiency metrics
    tokens_per_claim: Optional[float] = None
    tokens_per_validated_claim: Optional[float] = None

    # Most expensive stage
    most_expensive_stage: Optional[str] = None


class QueueMetrics(BaseModel):
    """Current queue state for pages in the pipeline."""
    queued: int = 0
    active: int = 0
    completed: int = 0
    failed: int = 0


class ResearchLiveStatus(BaseModel):
    """Real-time status of a running research session."""
    session_id: UUID
    current_stage: Optional[str] = None
    progress_percent: float = 0.0
    pages_processed: int = 0
    pages_remaining: int = 0
    current_url: Optional[str] = None
    elapsed_ms: float = 0.0
    current_round: Optional[int] = None
    queue_metrics: Optional[QueueMetrics] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None


class DebugReportSlowest(BaseModel):
    """Entry in slowest-items lists."""
    identifier: str
    duration_ms: float
    stage: Optional[str] = None
    metadata: Optional[dict] = None


class DebugReport(BaseModel):
    """Full debug report for a research session — the one endpoint you'll use constantly."""
    session_id: UUID
    durations: dict = {}
    token_usage: dict = {}
    slowest_pages: List[DebugReportSlowest] = []
    slowest_queries: List[DebugReportSlowest] = []
    slowest_llm_calls: List[DebugReportSlowest] = []
    most_expensive_stage: Optional[str] = None
    tokens_per_claim: Optional[float] = None
    tokens_per_validated_claim: Optional[float] = None


class LiveResearchStatus(BaseModel):
    """Detailed real-time snapshot of a running research session."""
    session_id: UUID
    current_stage: str
    progress_percent: float
    pages_completed: int
    pages_total: int
    claims_extracted: int
    validated_claims: int
    current_url: Optional[str] = None
    current_chunk: Optional[int] = None
    total_chunks: Optional[int] = None
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


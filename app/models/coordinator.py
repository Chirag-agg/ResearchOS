from uuid import UUID
from typing import List, Optional
from sqlmodel import SQLModel
from app.models.claim import ClaimRead


class ResearchRunResult(SQLModel):
    """
    Response DTO containing summary stats and top claims from a research pipeline run.
    """
    session_id: UUID
    question: str
    queries_generated: int
    results_found: int
    pages_fetched: int
    claims_extracted: int
    claims_supported: int
    claims_weak_support: int
    claims_unsupported: int
    top_claims: List[ClaimRead]


class IterativeResearchRequest(SQLModel):
    """
    Request DTO payload to trigger iterative loop research.
    """
    question: str
    max_rounds: Optional[int] = None
    confidence_threshold: Optional[float] = None
    session_id: Optional[UUID] = None



class IterativeResearchRoundMetrics(SQLModel):
    """
    DTO wrapping summary metrics for a single loop round.
    """
    round_number: int
    queries_generated: int
    results_found: int
    pages_fetched: int
    concepts_added: int
    coverage_score: float
    confidence_score: float
    knowledge_growth: int


class IterativeResearchRunResult(SQLModel):
    """
    Response DTO containing overall synthesis stats and loop round metrics.
    """
    session_id: UUID
    question: str
    rounds_executed: int
    final_coverage_score: float
    final_confidence_score: float
    total_concepts: int
    stopped_reason: str  # "threshold_reached", "max_rounds_reached", "failed"
    round_metrics: List[IterativeResearchRoundMetrics]


class IterativeResearchLaunchResponse(SQLModel):
    """
    Response DTO returned when the iterative pipeline is launched in the background.
    """
    session_id: UUID
    question: str
    status: str = "running"

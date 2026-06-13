from uuid import UUID
from typing import List
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

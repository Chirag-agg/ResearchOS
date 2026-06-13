from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class ClaimCandidate(BaseModel):
    """
    Internal validation schema for a single extracted claim candidate from LLM response.
    Used for validation and transformation before database persistence.
    """
    claim_text: str = PydanticField(..., min_length=5, description="Factual claim text")
    evidence_snippet: str = PydanticField(..., min_length=5, description="Verbatim snippet from source text supporting this claim")
    confidence_score: float = PydanticField(..., ge=0.0, le=1.0, description="LLM confidence score")


class ExtractedClaim(SQLModel, table=True):
    """
    SQLModel representing a stored factual claim extracted from a fetched page.
    Includes chunk metadata, hash for deduplication, and query tracking.
    """
    __tablename__ = "extracted_claims"

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
    query_id: UUID = Field(
        foreign_key="generated_queries.id",
        index=True,
        nullable=False
    )
    claim_text: str = Field(nullable=False)
    claim_hash: str = Field(nullable=False, index=True)
    evidence_snippet: str = Field(nullable=False)
    confidence_score: float = Field(nullable=False)
    source_url: str = Field(nullable=False)
    source_domain: str = Field(nullable=False, index=True)
    source_chunk_index: int = Field(nullable=False)
    source_chunk_hash: str = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class ClaimExtractRequest(SQLModel):
    """
    Request DTO payload to trigger claim extraction for a session.
    """
    session_id: UUID


class ClaimRead(SQLModel):
    """
    Response DTO containing properties of an extracted claim.
    """
    id: UUID
    page_id: UUID
    session_id: UUID
    query_id: UUID
    claim_text: str
    claim_hash: str
    evidence_snippet: str
    confidence_score: float
    source_url: str
    source_domain: str
    source_chunk_index: int
    source_chunk_hash: str
    created_at: datetime


class ClaimsResponse(SQLModel):
    """
    Response DTO containing the list of extracted claims.
    """
    claims: List[ClaimRead]

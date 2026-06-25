from uuid import UUID, uuid4
from typing import Optional, List
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON
from pydantic import BaseModel
from app.models.base import ProvenanceMixin

class TextSpan(BaseModel):
    """
    Represents a specific span of text within an artifact.
    """
    start: int
    end: int
    artifact_id: UUID
    sentence_index: Optional[int] = None
    paragraph_index: Optional[int] = None

class ObservationEvidenceLink(SQLModel, table=True):
    """
    Link table connecting an Observation to its reusable Evidence.
    """
    __tablename__ = "observation_evidence_links"
    observation_id: UUID = Field(foreign_key="observations.id", primary_key=True)
    evidence_id: UUID = Field(foreign_key="evidence.id", primary_key=True)

class ClaimEvidenceLink(SQLModel, table=True):
    """
    Link table connecting a Claim to its reusable Evidence.
    """
    __tablename__ = "claim_evidence_links"
    claim_id: UUID = Field(foreign_key="claims.id", primary_key=True)
    evidence_id: UUID = Field(foreign_key="evidence.id", primary_key=True)

class Evidence(ProvenanceMixin, table=True):
    """
    Independent, reusable evidence block.
    """
    __tablename__ = "evidence"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    # Store List of TextSpans as JSON
    text_spans: List[dict] = Field(default_factory=list, sa_column=Column(JSON))
    
    evidence_type: str = Field(nullable=False, description="e.g. text_span, table_cell, equation")
    excerpt: str = Field(nullable=False)
    match_score: int = Field(default=100, description="100=Exact, 80=Sentence, 60=Paragraph")
    confidence: float = Field(default=1.0)

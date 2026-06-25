from uuid import UUID, uuid4
from typing import Optional, List
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import SQLModel, Field, Relationship
from app.models.base import ProvenanceMixin

from enum import Enum

class ClaimPredicate(str, Enum):
    USES = "USES"
    TRAINS_ON = "TRAINS_ON"
    OUTPERFORMS = "OUTPERFORMS"
    IS_LIMITED_BY = "IS_LIMITED_BY"
    EVALUATED_ON = "EVALUATED_ON"
    INTRODUCES = "INTRODUCES"
    ACHIEVES = "ACHIEVES"
    REQUIRES = "REQUIRES"
    CAUSES = "CAUSES"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"

class ClaimCandidate(BaseModel):
    """
    Internal validation schema for a single extracted claim candidate from LLM response.
    Used for validation and transformation before database persistence.
    """
    subject: str = PydanticField(..., description="The subject entity text")
    predicate: str = PydanticField(..., description="The predicate, must be one of ClaimPredicate enum")
    object: str = PydanticField(..., description="The object entity text")
    
    evidence_snippet: str = PydanticField(..., min_length=5, description="Verbatim snippet from source text supporting this claim")
    predicate_confidence: float = PydanticField(..., ge=0.0, le=1.0, description="LLM confidence score for the predicate relationship")

class ClaimRead(BaseModel):
    id: UUID
    session_id: UUID
    subject_entity_id: UUID
    predicate: str
    object_entity_id: UUID
    overall_confidence: float

class ClaimsResponse(BaseModel):
    claims: List[ClaimRead]

class ClaimExtractRequest(BaseModel):
    page_id: UUID
    session_id: UUID

class Claim(ProvenanceMixin, table=True):
    """
    Relational assertion constructed from Observations.
    Modeled as RDF triples (subject -> predicate -> object).
    """
    __tablename__ = "claims"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stable_hash: str = Field(nullable=False, index=True, unique=True, description="SHA256 of subject_id + predicate + object_id")
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    
    subject_entity_id: UUID = Field(foreign_key="entities.id", index=True)
    predicate: str = Field(nullable=False, index=True)
    object_entity_id: UUID = Field(foreign_key="entities.id", index=True)
    
    entity_confidence: float = Field(default=1.0)
    grounding_confidence: float = Field(default=1.0)
    predicate_confidence: float = Field(default=1.0)
    overall_confidence: float = Field(default=1.0)
    
    # Relationships
    # evidence: List["Evidence"] = Relationship(back_populates="claim") 
    # (Leaving relationship comments for documentation, actual SQLModel wiring might need careful forward refs)

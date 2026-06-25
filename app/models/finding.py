from uuid import UUID, uuid4
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from app.models.base import ProvenanceMixin

class FindingDocumentLink(SQLModel, table=True):
    __tablename__ = "finding_document_links"
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", primary_key=True)

class FindingDomainLink(SQLModel, table=True):
    __tablename__ = "finding_domain_links"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", index=True)
    domain: str = Field(nullable=False, index=True)

class FindingSupportFindingLink(SQLModel, table=True):
    __tablename__ = "finding_support_finding_links"
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)
    supported_finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)

class FindingSupportClaimLink(SQLModel, table=True):
    __tablename__ = "finding_support_claim_links"
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)
    claim_id: UUID = Field(foreign_key="claims.id", ondelete="CASCADE", primary_key=True)

class FindingContradictingClaimLink(SQLModel, table=True):
    __tablename__ = "finding_contradicting_claim_links"
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)
    claim_id: UUID = Field(foreign_key="claims.id", ondelete="CASCADE", primary_key=True)

class Finding(ProvenanceMixin, table=True):
    """
    The contextual interpretation of Claims based on the Research Question.
    Contains reasoning.
    """
    __tablename__ = "findings"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stable_hash: str = Field(nullable=False, index=True, unique=True, description="SHA256 of title + summary")
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    
    title: str = Field(nullable=False)
    summary: str = Field(nullable=False)
    
    confidence_score: float = Field(default=0.0)
    novelty_score: float = Field(default=0.0)
    importance_score: float = Field(default=0.0)
    
    # Relationships
    supporting_documents: List["ParsedDocument"] = Relationship(link_model=FindingDocumentLink)
    supporting_domains: List[FindingDomainLink] = Relationship()
    supporting_claims: List["Claim"] = Relationship(link_model=FindingSupportClaimLink)
    contradicting_claims: List["Claim"] = Relationship(link_model=FindingContradictingClaimLink)
    
    # For finding to finding (it's slightly tricky in SQLModel, using the link model directly is safer if self-referential)
    # supporting_findings: List["Finding"] = Relationship(link_model=FindingSupportFindingLink)

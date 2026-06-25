from uuid import UUID, uuid4
from typing import Optional, List
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, String
from sqlalchemy import Enum as SAEnum
from app.models.base import ProvenanceMixin

class InsightType(str, Enum):
    CONSENSUS = "CONSENSUS"
    TREND = "TREND"
    SCALING_LAW = "SCALING_LAW"
    CONTRADICTION = "CONTRADICTION"
    GAP = "GAP"

class InsightFindingLink(SQLModel, table=True):
    __tablename__ = "insight_finding_links"
    insight_id: UUID = Field(foreign_key="insights.id", ondelete="CASCADE", primary_key=True)
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)

class Insight(ProvenanceMixin, table=True):
    """
    A macro-conclusion requiring multiple independent findings.
    """
    __tablename__ = "insights"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stable_hash: str = Field(nullable=False, index=True, unique=True, description="SHA256 of sorted primary entities + research question hash + cluster type")
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    
    type: InsightType = Field(sa_column=Column(SAEnum(InsightType, native_enum=False), nullable=False, index=True))
    text: str = Field(nullable=False)
    
    confidence_score: float = Field(default=0.0)
    contradictions_detected: bool = Field(default=False)
    
    supporting_findings: List["Finding"] = Relationship(link_model=InsightFindingLink)

from uuid import UUID, uuid4
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime

class ReportSectionItem(SQLModel, table=True):
    """
    Mapping between a report section and underlying knowledge objects.
    """
    __tablename__ = "report_section_items"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    section_id: UUID = Field(foreign_key="report_sections.id", ondelete="CASCADE", index=True)
    
    # Optional foreign keys to knowledge objects depending on section
    insight_id: Optional[UUID] = Field(default=None, foreign_key="insights.id")
    finding_id: Optional[UUID] = Field(default=None, foreign_key="findings.id")
    claim_id: Optional[UUID] = Field(default=None, foreign_key="claims.id")
    document_id: Optional[UUID] = Field(default=None, foreign_key="parsed_documents.id")
    
    # To maintain deterministic ordering within the section
    order_index: int = Field(default=0)
    
    section: "ReportSection" = Relationship(back_populates="items")

class ReportSection(SQLModel, table=True):
    """
    A structural block of the report.
    """
    __tablename__ = "report_sections"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    report_id: UUID = Field(foreign_key="research_reports.id", ondelete="CASCADE", index=True)
    
    section_type: str = Field(nullable=False) # E.g., "Executive Summary", "Contradictions"
    title: str = Field(nullable=False)
    order_index: int = Field(nullable=False)
    
    # E.g., raw computed limitations or statistics serialized as JSON string, if not backed by explicit items
    computed_content: Optional[str] = Field(default=None)
    
    report: "ResearchReport" = Relationship(back_populates="sections")
    items: List[ReportSectionItem] = Relationship(back_populates="section", cascade_delete=True)

class ResearchReport(SQLModel, table=True):
    """
    The final assembled presentation of the synthesized session knowledge.
    """
    __tablename__ = "research_reports"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    
    title: str = Field(nullable=False)
    report_version: int = Field(default=1)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    sections: List[ReportSection] = Relationship(back_populates="report", cascade_delete=True)

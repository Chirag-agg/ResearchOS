from uuid import UUID, uuid4
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from app.models.base import ProvenanceMixin

class ResearchMemoryStringItem(SQLModel, table=True):
    __tablename__ = "research_memory_strings"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    memory_id: UUID = Field(foreign_key="research_memory.id", ondelete="CASCADE", index=True)
    type: str = Field(nullable=False, index=True) # e.g. "future_work", "open_question", "failed_query", "successful_query"
    text: str = Field(nullable=False)

class ResearchMemoryEntityLink(SQLModel, table=True):
    __tablename__ = "research_memory_entity_links"
    memory_id: UUID = Field(foreign_key="research_memory.id", ondelete="CASCADE", primary_key=True)
    entity_id: UUID = Field(foreign_key="entities.id", ondelete="CASCADE", primary_key=True)

class ResearchMemoryFindingLink(SQLModel, table=True):
    __tablename__ = "research_memory_finding_links"
    memory_id: UUID = Field(foreign_key="research_memory.id", ondelete="CASCADE", primary_key=True)
    finding_id: UUID = Field(foreign_key="findings.id", ondelete="CASCADE", primary_key=True)

class ResearchMemory(ProvenanceMixin, table=True):
    """
    The iterative, living state of the investigation.
    Injected into the Query Planner to prevent redundant searches.
    """
    __tablename__ = "research_memory"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    
    question: str = Field(nullable=False)
    
    # Relationships
    string_items: List[ResearchMemoryStringItem] = Relationship()
    known_entities: List["Entity"] = Relationship(link_model=ResearchMemoryEntityLink)
    known_findings: List["Finding"] = Relationship(link_model=ResearchMemoryFindingLink)

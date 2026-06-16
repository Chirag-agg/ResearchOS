from datetime import datetime
from uuid import UUID
from typing import List, Optional
from sqlmodel import SQLModel, Field


class ReasoningValidationSummary(SQLModel):
    supported: int = 0
    weak_support: int = 0
    unsupported: int = 0


class ReasoningSourceRead(SQLModel):
    source_id: UUID
    page_id: UUID
    query_id: Optional[UUID] = None
    title: str
    url: str
    domain: str
    reason: str
    quality_score: float
    credibility_score: float


class ReasoningRoundRead(SQLModel):
    round_number: int
    title: str
    generated_queries: List[str] = Field(default_factory=list)
    sources_visited: List[ReasoningSourceRead] = Field(default_factory=list)
    pages_analyzed: List[str] = Field(default_factory=list)
    knowledge_added: List[str] = Field(default_factory=list)
    claims_added: List[str] = Field(default_factory=list)
    validation_results: ReasoningValidationSummary = Field(default_factory=ReasoningValidationSummary)
    duration_ms: float = 0.0
    token_cost: int = 0
    belief_before: str = ""
    belief_after: str = ""
    what_changed: str = ""
    new_evidence: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    gap_ids: List[str] = Field(default_factory=list)
    followup_ids: List[str] = Field(default_factory=list)


class ReasoningGapRead(SQLModel):
    id: UUID
    round_number: int
    topic: str
    reason: str
    priority: str
    why_identified: str
    followup_ids: List[str] = Field(default_factory=list)


class ReasoningFollowupRead(SQLModel):
    id: UUID
    gap_topic: str
    reason: str
    priority: str
    generated_queries: List[str] = Field(default_factory=list)
    sources_found: List[str] = Field(default_factory=list)
    knowledge_added: List[str] = Field(default_factory=list)


class ReasoningDecisionRead(SQLModel):
    id: str
    kind: str
    round_number: Optional[int] = None
    title: str
    reason: str
    evidence: List[str] = Field(default_factory=list)


class ReasoningEvolutionRead(SQLModel):
    id: str
    round_number: int
    believed: str
    changed: str
    new_evidence: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)


class ReasoningTreeNodeRead(SQLModel):
    id: str
    parent_id: Optional[str] = None
    label: str
    kind: str
    round_number: Optional[int] = None
    detail: Optional[str] = None
    order: int = 0


class ReasoningResponse(SQLModel):
    session_id: UUID
    question: str
    final_conclusions: List[str] = Field(default_factory=list)
    tree_nodes: List[ReasoningTreeNodeRead] = Field(default_factory=list)
    rounds: List[ReasoningRoundRead] = Field(default_factory=list)
    gaps: List[ReasoningGapRead] = Field(default_factory=list)
    followups: List[ReasoningFollowupRead] = Field(default_factory=list)
    decision_cards: List[ReasoningDecisionRead] = Field(default_factory=list)
    evolution: List[ReasoningEvolutionRead] = Field(default_factory=list)

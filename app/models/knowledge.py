from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class RelationshipType(str, Enum):
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    SUPPORTS = "supports"
    CONTRASTS_WITH = "contrasts_with"


class KnowledgeNode(SQLModel, table=True):
    """
    SQLModel entity representing a concept (node) in the knowledge base graph.
    """
    __tablename__ = "knowledge_nodes"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False
    )
    concept: str = Field(nullable=False, index=True)
    description: str = Field(nullable=False)
    confidence: float = Field(nullable=False)
    source_count: int = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class KnowledgeEdge(SQLModel, table=True):
    """
    SQLModel entity representing a directed relationship (edge) between concepts in the graph.
    """
    __tablename__ = "knowledge_edges"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False
    )
    source_node: UUID = Field(
        foreign_key="knowledge_nodes.id",
        index=True,
        nullable=False
    )
    target_node: UUID = Field(
        foreign_key="knowledge_nodes.id",
        index=True,
        nullable=False
    )
    relationship: RelationshipType = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class KnowledgeBuildRequest(SQLModel):
    """
    Request DTO payload to trigger knowledge base compilation for a session.
    """
    session_id: UUID


class NodeRead(SQLModel):
    """
    Response DTO containing properties of a knowledge node.
    """
    id: UUID
    session_id: UUID
    concept: str
    description: str
    confidence: float
    source_count: int
    created_at: datetime


class EdgeRead(SQLModel):
    """
    Response DTO containing properties of a knowledge edge.
    """
    id: UUID
    session_id: UUID
    source_node: UUID
    target_node: UUID
    relationship: RelationshipType
    created_at: datetime


class KnowledgeBuildResponse(SQLModel):
    """
    Response DTO wrapping the constructed knowledge nodes and edges.
    """
    nodes: List[NodeRead]
    edges: List[EdgeRead]

from uuid import UUID, uuid4
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from app.models.base import ProvenanceMixin

class EntityAlias(SQLModel, table=True):
    __tablename__ = "entity_aliases"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entity_id: UUID = Field(foreign_key="entities.id", ondelete="CASCADE", index=True)
    alias: str = Field(nullable=False, index=True)
    
    entity: "Entity" = Relationship(back_populates="aliases")

class EntityExternalId(SQLModel, table=True):
    __tablename__ = "entity_external_ids"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entity_id: UUID = Field(foreign_key="entities.id", ondelete="CASCADE", index=True)
    source: str = Field(nullable=False) # e.g. "arxiv", "doi"
    external_id: str = Field(nullable=False)
    
    entity: "Entity" = Relationship(back_populates="external_ids")

class Entity(ProvenanceMixin, table=True):
    __tablename__ = "entities"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stable_hash: str = Field(nullable=False, index=True, unique=True, description="SHA256 of canonical_name")
    
    canonical_name: str = Field(nullable=False, index=True)
    entity_type: str = Field(nullable=False, index=True) # E.g. "model", "metric", "dataset"
    description: Optional[str] = Field(default=None)
    
    # Relationships
    aliases: List[EntityAlias] = Relationship(back_populates="entity")
    external_ids: List[EntityExternalId] = Relationship(back_populates="entity")
    
    # Optional embedding field, stored as bytes for SQLite compatibility or separate vector DB
    embedding: Optional[bytes] = Field(default=None)

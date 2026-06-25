from uuid import UUID, uuid4
from typing import Optional, List
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, String, JSON
from sqlalchemy import Enum as SAEnum
from app.models.base import ProvenanceMixin
from app.pipeline.ir import SectionRole

class BlockType(str, Enum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    QUOTE = "QUOTE"
    CODE = "CODE"
    TABLE = "TABLE"
    FIGURE = "FIGURE"
    EQUATION = "EQUATION"
    LIST = "LIST"
    REFERENCE = "REFERENCE"

class ParsedDocument(ProvenanceMixin, table=True):
    __tablename__ = "parsed_documents"
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    page_id: UUID = Field(foreign_key="fetched_pages.id", ondelete="CASCADE", index=True)
    
    cleaned_text: str = Field(nullable=False)
    limitations: Optional[str] = Field(default=None)
    future_work: Optional[str] = Field(default=None)
    negative_results: Optional[str] = Field(default=None)
    
    # Parser telemetry
    document_quality_score: float = Field(default=1.0)
    cleaner_version: str = Field(default="1.0.0")
    parser_version: str = Field(default="1.0.0")
    section_classifier_version: str = Field(default="1.0.0")
    table_extractor_version: str = Field(default="1.0.0")
    figure_extractor_version: str = Field(default="1.0.0")
    reference_parser_version: str = Field(default="1.0.0")
    summary_version: str = Field(default="1.0.0")
    
    parse_errors: Optional[str] = Field(default=None)
    source_encoding: str = Field(default="utf-8")
    language: str = Field(default="en")
    
    # Relationships
    artifacts: List["DocumentArtifact"] = Relationship(back_populates="document")
    tables: List["DocumentTable"] = Relationship(back_populates="document")
    figures: List["DocumentFigure"] = Relationship(back_populates="document")
    equations: List["DocumentEquation"] = Relationship(back_populates="document")
    references: List["Reference"] = Relationship(back_populates="document")
    summary: Optional["DocumentSummary"] = Relationship(back_populates="document")
    entity_mentions: List["EntityMention"] = Relationship(back_populates="document")

class DocumentArtifact(ProvenanceMixin, table=True):
    __tablename__ = "document_artifacts"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    artifact_type: str = Field(nullable=False, description="E.g. PARAGRAPH, TABLE_CAPTION")
    content: str = Field(nullable=False)
    section_role: SectionRole = Field(sa_column=Column(SAEnum(SectionRole, native_enum=False), nullable=False, default=SectionRole.UNKNOWN))
    sequence_index: int = Field(default=0)
    
    # Structural Features
    struct_contains_math: bool = Field(default=False)
    struct_contains_table: bool = Field(default=False)
    struct_contains_equation: bool = Field(default=False)
    struct_contains_reference: bool = Field(default=False)
    
    # Semantic Features
    sem_contains_metric: bool = Field(default=False)
    sem_contains_dataset: bool = Field(default=False)
    sem_contains_code: bool = Field(default=False)
    
    # Statistical Features
    stat_sentence_count: int = Field(default=0)
    stat_citation_density: float = Field(default=0.0)
    stat_numeric_density: float = Field(default=0.0)
    stat_importance_score: float = Field(default=0.5)
    
    document: ParsedDocument = Relationship(back_populates="artifacts")
    entity_mentions: List["EntityMention"] = Relationship(back_populates="artifact")

class EntityMention(ProvenanceMixin, table=True):
    __tablename__ = "entity_mentions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    artifact_id: Optional[UUID] = Field(default=None, foreign_key="document_artifacts.id", ondelete="CASCADE")
    
    mention_text: str = Field(nullable=False, index=True)
    canonical_entity_id: Optional[UUID] = Field(default=None, foreign_key="entities.id", index=True)
    
    document: ParsedDocument = Relationship(back_populates="entity_mentions")
    artifact: Optional[DocumentArtifact] = Relationship(back_populates="entity_mentions")

class DocumentTable(ProvenanceMixin, table=True):
    __tablename__ = "document_tables"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    title: Optional[str] = Field(default=None)
    caption: Optional[str] = Field(default=None)
    markdown_content: str = Field(nullable=False)
    
    # Logical Grid IR (e.g. nested lists of cells with row/col spans)
    logical_grid: dict = Field(default_factory=dict, sa_column=Column(JSON))
    has_header_row: bool = Field(default=True)
    has_stub_column: bool = Field(default=False)
    
    document: ParsedDocument = Relationship(back_populates="tables")

class DocumentFigure(ProvenanceMixin, table=True):
    __tablename__ = "document_figures"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    caption: str = Field(nullable=False)
    image_url: Optional[str] = Field(default=None)
    
    document: ParsedDocument = Relationship(back_populates="figures")

class DocumentEquation(ProvenanceMixin, table=True):
    __tablename__ = "document_equations"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    latex: str = Field(nullable=False)
    mathml: Optional[str] = Field(default=None)
    is_inline: bool = Field(default=False)
    
    document: ParsedDocument = Relationship(back_populates="equations")

class Reference(ProvenanceMixin, table=True):
    __tablename__ = "document_references"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    
    citation_text: str = Field(nullable=False)
    authors: Optional[str] = Field(default=None)
    year: Optional[int] = Field(default=None)
    title: Optional[str] = Field(default=None)
    url: Optional[str] = Field(default=None)
    doi: Optional[str] = Field(default=None, index=True)
    arxiv_id: Optional[str] = Field(default=None, index=True)
    pmid: Optional[str] = Field(default=None, index=True)
    
    document: ParsedDocument = Relationship(back_populates="references")
    citations_made: List["CitationEdge"] = Relationship(back_populates="source_reference")

class CitationEdge(ProvenanceMixin, table=True):
    __tablename__ = "citation_edges"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True)
    source_reference_id: UUID = Field(foreign_key="document_references.id", ondelete="CASCADE", index=True)
    
    # The external paper being cited
    target_doi: Optional[str] = Field(default=None, index=True)
    target_arxiv_id: Optional[str] = Field(default=None, index=True)
    target_title: Optional[str] = Field(default=None, index=True)
    
    source_reference: Reference = Relationship(back_populates="citations_made")

class DocumentSummary(ProvenanceMixin, table=True):
    __tablename__ = "document_summaries"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(foreign_key="parsed_documents.id", ondelete="CASCADE", index=True, unique=True)
    
    research_type: str = Field(description="E.g. Survey, Benchmark, Case Study, etc.")
    paper_type: str = Field(description="E.g. Academic, Blog, Documentation, News")
    main_contribution: str = Field(nullable=False)
    main_methods: str = Field(nullable=False)
    main_results: str = Field(nullable=False)
    main_limitations: str = Field(nullable=False)
    main_datasets: str = Field(nullable=False)
    future_work: str = Field(nullable=False)
    confidence: float = Field(default=1.0)
    
    document: ParsedDocument = Relationship(back_populates="summary")

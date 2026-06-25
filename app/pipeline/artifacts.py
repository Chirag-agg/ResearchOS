from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class Artifact(BaseModel):
    """
    Base runtime abstraction for anything extracted in the processing pipeline.
    This is NOT persisted to SQL; it lives purely in memory until final observation/finding transformation.
    """
    id: str
    artifact_type: str
    text: str
    original_html_offset: int
    cleaned_offset: int
    final_offset: int
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentBlock(Artifact):
    artifact_type: str = "document_block"
    block_type: str # e.g. "HEADING", "PARAGRAPH", "LIST"
    section_id: Optional[str] = None

class TableCell(Artifact):
    artifact_type: str = "table_cell"
    table_id: str
    row_idx: int
    col_idx: int
    is_header: bool = False

class FigureCaption(Artifact):
    artifact_type: str = "figure_caption"
    figure_id: str

class Equation(Artifact):
    artifact_type: str = "equation"
    latex_content: str

class CodeSnippet(Artifact):
    artifact_type: str = "code_snippet"
    language: Optional[str] = None

class ReferenceArtifact(Artifact):
    artifact_type: str = "reference"
    citation_id: Optional[str] = None

class MetadataArtifact(Artifact):
    artifact_type: str = "metadata"
    key: str
    value: Any

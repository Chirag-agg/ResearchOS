from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum
import hashlib

# ---------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------

class DocumentFingerprints(BaseModel):
    structural: str = Field(description="Hash of heading/table/reference hierarchy")
    semantic: str = Field(description="Hash of summaries and entities")
    content: str = Field(description="Hash of normalized text")

# ---------------------------------------------------------
# Source Document Adapter Model
# ---------------------------------------------------------

class SourceDocument(BaseModel):
    id: str
    source_type: str # "HTML", "PDF", etc.
    raw_content: bytes
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ---------------------------------------------------------
# Immutable Document Nodes (IR)
# ---------------------------------------------------------
# Pydantic automatically handles frozen=True to enforce immutability.

class NodeOffsets(BaseModel):
    html_offset: int = -1
    dom_offset: int = -1
    clean_offset: int = -1
    artifact_offset: int = -1

class ProvenanceMetadata(BaseModel):
    source_xpath: str = ""
    source_tag: str = ""
    source_css_selector: str = ""
    parser_stage: str = ""

class DocumentNode(BaseModel):
    """Base immutable node for the Document IR."""
    id: str
    node_type: str = "DOCUMENT_NODE"
    text: str = ""
    
    # We store references as strings/IDs if needed, or nest directly for pure trees.
    # To keep it truly immutable and tree-like, children are nested objects.
    children: List["DocumentNode"] = Field(default_factory=list)
    
    attributes: Dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0
    section_hint: Optional[str] = None
    
    offsets: NodeOffsets = Field(default_factory=NodeOffsets)
    provenance: ProvenanceMetadata = Field(default_factory=ProvenanceMetadata)

    class Config:
        frozen = True

# Specific Node Subclasses

class ParagraphNode(DocumentNode):
    node_type: Literal["PARAGRAPH"] = "PARAGRAPH"

class HeadingNode(DocumentNode):
    node_type: Literal["HEADING"] = "HEADING"
    level: int = 1
    number: Optional[str] = None

class TableCellNode(DocumentNode):
    node_type: Literal["TABLE_CELL"] = "TABLE_CELL"
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1

class TableRowNode(DocumentNode):
    node_type: Literal["TABLE_ROW"] = "TABLE_ROW"
    children: List[TableCellNode] = Field(default_factory=list)

class TableNode(DocumentNode):
    node_type: Literal["TABLE"] = "TABLE"
    caption: Optional[str] = None
    children: List[TableRowNode] = Field(default_factory=list)

class FigureNode(DocumentNode):
    node_type: Literal["FIGURE"] = "FIGURE"
    caption: Optional[str] = None
    alt_text: Optional[str] = None
    url: Optional[str] = None

class EquationNode(DocumentNode):
    node_type: Literal["EQUATION"] = "EQUATION"
    latex: Optional[str] = None
    mathml: Optional[str] = None
    display_mode: bool = False

class CodeNode(DocumentNode):
    node_type: Literal["CODE"] = "CODE"
    language: Optional[str] = None

class ReferenceNode(DocumentNode):
    node_type: Literal["REFERENCE"] = "REFERENCE"
    doi: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None

class ListNode(DocumentNode):
    node_type: Literal["LIST"] = "LIST"
    ordered: bool = False

class ListItemNode(DocumentNode):
    node_type: Literal["LIST_ITEM"] = "LIST_ITEM"

class SectionRole(str, Enum):
    ABSTRACT = "ABSTRACT"
    INTRODUCTION = "INTRODUCTION"
    BACKGROUND = "BACKGROUND"
    RELATED_WORK = "RELATED_WORK"
    METHODS = "METHODS"
    EXPERIMENTS = "EXPERIMENTS"
    RESULTS = "RESULTS"
    DISCUSSION = "DISCUSSION"
    LIMITATIONS = "LIMITATIONS"
    FUTURE_WORK = "FUTURE_WORK"
    CONCLUSION = "CONCLUSION"
    APPENDIX = "APPENDIX"
    REFERENCES = "REFERENCES"
    ACKNOWLEDGEMENTS = "ACKNOWLEDGEMENTS"
    UNKNOWN = "UNKNOWN"

class EvidenceLevel(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    SUPPLEMENTARY = "SUPPLEMENTARY"
    UNKNOWN = "UNKNOWN"

class ResearchType(str, Enum):
    SURVEY = "SURVEY"
    BENCHMARK = "BENCHMARK"
    EMPIRICAL = "EMPIRICAL"
    THEORETICAL = "THEORETICAL"
    REPRODUCTION = "REPRODUCTION"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"

class SectionClassification(BaseModel):
    role: SectionRole = SectionRole.UNKNOWN
    confidence: float = 1.0
    classifier: str = "rule_based"
    evidence: List[str] = Field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.UNKNOWN
    research_type: ResearchType = ResearchType.UNKNOWN

class SectionNode(DocumentNode):
    node_type: Literal["SECTION"] = "SECTION"
    title: str = ""
    classification: SectionClassification = Field(default_factory=SectionClassification)


# Required for self-referencing tree Pydantic resolution
DocumentNode.model_rebuild()
TableRowNode.model_rebuild()
TableNode.model_rebuild()


# ---------------------------------------------------------
# ID Generation
# ---------------------------------------------------------
def generate_deterministic_id(document_fingerprint: str, xpath: str, text: str) -> str:
    """
    Generates a deterministic structural ID.
    SHA256(document_fingerprint + xpath + text)
    """
    payload = f"{document_fingerprint}|{xpath}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

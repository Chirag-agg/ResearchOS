from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID

class ObservationContext(BaseModel):
    """
    Strict, constrained context provided to the LLM for extracting observations.
    """
    research_question: str
    section_type: str
    current_artifact_id: UUID
    current_artifact_text: str
    previous_artifact_text: Optional[str] = None
    next_artifact_text: Optional[str] = None
    document_summary: str = ""
    known_entities: List[str] = Field(default_factory=list)

class ObservationPrompt(BaseModel):
    """
    Explicit versioning and tracking of the prompt used to extract observations.
    """
    version: str
    template_hash: str
    variables: Dict[str, Any]
    rendered_prompt: str

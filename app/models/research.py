from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID


class ResearchQuestion(BaseModel):
    """
    DTO for input research question.
    """
    question: str = Field(
        ...,
        description="The primary research question to plan queries for.",
        examples=["Best vector databases for RAG"]
    )
    session_id: Optional[UUID] = None



class ResearchQueries(BaseModel):
    """
    DTO for returning planned search queries.
    """
    queries: List[str] = Field(
        ...,
        description="A list of 5 high-quality, distinct search queries derived from the input question."
    )

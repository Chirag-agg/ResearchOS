from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field

def get_utc_now() -> datetime:
    """
    Returns the current UTC time as a timezone-naive datetime object.
    SQLite doesn't natively handle timezone offsets cleanly; storing naive UTC datetime
    objects is the standard best practice for databases.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ProvenanceMixin(SQLModel):
    """
    Universal Provenance Interface.
    Every object in the system inherits these fields to guarantee 100% traceability.
    """
    created_by: str = Field(nullable=False, description="Which service/agent produced it")
    pipeline_stage: str = Field(nullable=False, description="Current stage of processing")
    round_idx: int = Field(default=0, nullable=False, description="The iterative research round (e.g., 0, 1, 2)")
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False, description="UTC creation time")
    prompt_hash: Optional[str] = Field(default=None, description="The specific LLM prompt version used")

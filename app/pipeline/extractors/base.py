import time
from typing import Generic, TypeVar, List, Dict, Any
from pydantic import BaseModel, Field
from app.pipeline.core import PipelineStage, PipelineContext
from app.pipeline.ir import DocumentNode

T = TypeVar("T")

class ExtractorResult(BaseModel, Generic[T]):
    artifacts: List[T]
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)

class ArtifactExtractorStage(PipelineStage[DocumentNode, ExtractorResult[T]], Generic[T]):
    """
    Base class for Specialized Extractors (Phase 3A.6).
    Consumes the frozen IR tree and emits ExtractorResult[T].
    """
    
    def extract(self, root: DocumentNode, context: PipelineContext) -> ExtractorResult[T]:
        raise NotImplementedError
        
    async def process(self, root: DocumentNode, context: PipelineContext) -> ExtractorResult[T]:
        # Extractor stages are synchronous for now, though they could be async if they do network calls.
        return self.extract(root, context)

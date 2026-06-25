import hashlib
import time
import json
from enum import Enum
from typing import Generic, TypeVar, Dict, Any, List, Optional
from pydantic import BaseModel, Field
from app.pipeline.artifacts import Artifact

T_IN = TypeVar("T_IN")
T_OUT = TypeVar("T_OUT")

class StageStatus(str, Enum):
    SUCCESS = "SUCCESS"
    SUCCESS_WITH_WARNINGS = "SUCCESS_WITH_WARNINGS"
    RECOVERED = "RECOVERED"
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    SKIPPED = "SKIPPED"
    CACHED = "CACHED"

class PipelineContext(BaseModel):
    session_id: str
    document_id: str
    research_question: Optional[str] = None
    round_idx: int = 0
    pipeline_config: Dict[str, Any] = Field(default_factory=dict)
    # Stubs for what should be actual logging/telemetry/cache injection
    cache_enabled: bool = True
    benchmark_mode: bool = False
    
    def hash_config(self) -> str:
        # Simple deterministic hash of config
        return hashlib.sha256(json.dumps(self.pipeline_config, sort_keys=True).encode("utf-8")).hexdigest()

class StageResult(BaseModel, Generic[T_OUT]):
    status: StageStatus
    output: Optional[T_OUT] = None
    metrics: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Artifact] = Field(default_factory=list)
    
    next_context: Optional[PipelineContext] = None
    cache_key: Optional[str] = None
    execution_time_ms: float = 0.0
    confidence: float = 1.0
    version: str

class PipelineStage(Generic[T_IN, T_OUT]):
    name: str
    version: str
    
    async def process(self, input_data: T_IN, context: PipelineContext) -> StageResult[T_OUT]:
        raise NotImplementedError
    
    def _generate_cache_key(self, input_hash: str, context: PipelineContext) -> str:
        payload = f"{input_hash}|{self.name}|{self.version}|{context.hash_config()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

class PipelineRegistry:
    _stages: Dict[str, type] = {}

    @classmethod
    def register(cls, stage_cls: type):
        if not hasattr(stage_cls, "name"):
            raise ValueError(f"Stage {stage_cls.__name__} must define a 'name' attribute.")
        cls._stages[stage_cls.name] = stage_cls

    @classmethod
    def get(cls, name: str) -> type:
        return cls._stages[name]
    
    @classmethod
    def get_all(cls) -> Dict[str, type]:
        return cls._stages

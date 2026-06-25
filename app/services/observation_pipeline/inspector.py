import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class TraceEvent(BaseModel):
    stage_name: str
    timestamp: str
    duration_ms: float
    payload: Any
    passed: bool = True
    warnings: List[str] = []
    errors: List[str] = []

class ObservationTrace(BaseModel):
    """
    Complete timeline of an observation extraction lifecycle.
    """
    trace_id: str
    artifact_id: str
    created_at: str
    events: List[TraceEvent] = []
    
    def add_event(self, stage: str, payload: Any, passed: bool = True, warnings: List[str] = None, errors: List[str] = None, duration_ms: float = 0.0):
        self.events.append(TraceEvent(
            stage_name=stage,
            timestamp=datetime.utcnow().isoformat(),
            duration_ms=duration_ms,
            payload=payload,
            passed=passed,
            warnings=warnings or [],
            errors=errors or []
        ))

class TraceRenderer(ABC):
    @abstractmethod
    def render(self, trace: ObservationTrace) -> Any:
        pass

class JSONRenderer(TraceRenderer):
    def render(self, trace: ObservationTrace) -> str:
        return trace.model_dump_json(indent=2)

class RichRenderer(TraceRenderer):
    def render(self, trace: ObservationTrace) -> str:
        """
        In a real terminal, we would use rich.console and rich.panel here.
        Returning string representation for simplicity if rich is unavailable.
        """
        output = [f"=== Trace: {trace.trace_id} (Artifact: {trace.artifact_id}) ==="]
        for idx, event in enumerate(trace.events):
            status = "PASS" if event.passed else "FAIL"
            color = "green" if event.passed else "red"
            
            output.append(f"\n[{idx+1}] {event.stage_name} ({event.duration_ms}ms) - [{status}]")
            if event.errors:
                output.append(f"    Errors: {', '.join(event.errors)}")
            if event.warnings:
                output.append(f"    Warnings: {', '.join(event.warnings)}")
                
        return "\n".join(output)

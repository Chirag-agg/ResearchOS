from abc import ABC, abstractmethod
from typing import Dict, Any
from benchmarks.core.dataset import BenchmarkDataset

class EvaluatorResult:
    def __init__(self, score: float, details: Dict[str, Any] = None):
        self.score = score
        self.details = details or {}

class BaseEvaluator(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def evaluate(self, run_artifacts: Dict[str, Any], dataset: BenchmarkDataset) -> EvaluatorResult:
        pass

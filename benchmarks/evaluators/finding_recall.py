from typing import Dict, Any
from .base import BaseEvaluator, EvaluatorResult
from benchmarks.core.dataset import BenchmarkDataset

class FindingRecallEvaluator(BaseEvaluator):
    @property
    def name(self) -> str: return "finding_recall"
    async def evaluate(self, run_artifacts: Dict[str, Any], dataset: BenchmarkDataset) -> EvaluatorResult:
        claims = run_artifacts.get("validated_claims", [])
        required = dataset.background.required_findings if dataset.background else []
        return EvaluatorResult(score=len(claims) / max(1, len(required)), details={"found": len(claims)})

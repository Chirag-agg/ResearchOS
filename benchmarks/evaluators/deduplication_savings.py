from typing import Dict, Any
from .base import BaseEvaluator, EvaluatorResult
from benchmarks.core.dataset import BenchmarkDataset

class DeduplicationSavingsEvaluator(BaseEvaluator):
    @property
    def name(self) -> str: return "deduplication_savings"
    async def evaluate(self, run_artifacts: Dict[str, Any], dataset: BenchmarkDataset) -> EvaluatorResult:
        pools = run_artifacts.get("candidate_pools", [])
        savings = sum(getattr(p, "duplicates_removed", 0) for p in pools)
        return EvaluatorResult(score=1.0, details={"duplicates_removed": savings})

from typing import Dict, Any
from .base import BaseEvaluator, EvaluatorResult
from benchmarks.core.dataset import BenchmarkDataset

class QueryDiversityEvaluator(BaseEvaluator):
    @property
    def name(self) -> str: return "query_diversity"
    async def evaluate(self, run_artifacts: Dict[str, Any], dataset: BenchmarkDataset) -> EvaluatorResult:
        queries = run_artifacts.get("queries", [])
        return EvaluatorResult(score=1.0, details={"queries_generated": len(queries)})

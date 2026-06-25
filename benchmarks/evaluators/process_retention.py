from typing import Dict, Any
from .base import BaseEvaluator, EvaluatorResult
from benchmarks.core.dataset import BenchmarkDataset

class ProcessRetentionEvaluator(BaseEvaluator):
    @property
    def name(self) -> str: return "process_retention"
    async def evaluate(self, run_artifacts: Dict[str, Any], dataset: BenchmarkDataset) -> EvaluatorResult:
        nodes = run_artifacts.get("graph_nodes", [])
        edges = run_artifacts.get("graph_edges", [])
        return EvaluatorResult(score=1.0 if len(nodes) > 0 else 0.0, details={"nodes": len(nodes), "edges": len(edges)})

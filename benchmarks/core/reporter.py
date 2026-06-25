import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from benchmarks.evaluators import BaseEvaluator, EvaluatorResult
from benchmarks.core.dataset import BenchmarkDataset

logger = logging.getLogger(__name__)

class BenchmarkReporter:
    def __init__(self, run_id: str, base_dir: Path):
        self.run_id = run_id
        self.run_dir = base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.results = {}

    def add_result(self, evaluator_name: str, result: EvaluatorResult):
        self.results[evaluator_name] = {
            "score": result.score,
            "details": result.details
        }

    def generate(self, dataset: BenchmarkDataset):
        json_path = self.run_dir / "benchmark_report.json"
        md_path = self.run_dir / "benchmark_report.md"

        # 1. JSON Report
        report_data = {
            "run_id": self.run_id,
            "dataset_id": dataset.dataset_id,
            "results": self.results
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        # 2. Markdown Report
        md_content = f"# Benchmark Report: {dataset.dataset_id}\n\n"
        md_content += f"**Run ID**: `{self.run_id}`\n\n"
        
        md_content += "## Overall Scores\n\n"
        md_content += "| Evaluator | Score |\n"
        md_content += "|-----------|-------|\n"
        for name, data in self.results.items():
            # Format score nicely (assuming it's a float between 0 and 1)
            score_fmt = f"{data['score']*100:.1f}%" if data['score'] <= 1.0 else f"{data['score']:.2f}"
            md_content += f"| {name} | {score_fmt} |\n"

        md_content += "\n## Detailed Results\n\n"
        for name, data in self.results.items():
            md_content += f"### {name}\n"
            md_content += "```json\n"
            # Dump details without overwhelming size, perhaps truncate
            md_content += json.dumps(data["details"], indent=2)[:2000]
            if len(json.dumps(data["details"])) > 2000:
                md_content += "\n... (truncated)"
            md_content += "\n```\n\n"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info(f"Generated benchmark reports in {self.run_dir}")

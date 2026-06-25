import asyncio
import argparse
import sys
import uuid
import logging
from pathlib import Path
from datetime import datetime

# Setup basic logging for CLI
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from benchmarks.core.dataset import load_dataset
from benchmarks.core.collector import BenchmarkCollector
from benchmarks.core.runner import BenchmarkRunner
from benchmarks.core.reporter import BenchmarkReporter
from benchmarks.evaluators import FindingRecallEvaluator, ProcessRetentionEvaluator
from benchmarks.evaluators.query_diversity import QueryDiversityEvaluator
from benchmarks.evaluators.result_diversity import ResultDiversityEvaluator
from benchmarks.evaluators.deduplication_savings import DeduplicationSavingsEvaluator
from benchmarks.evaluators.connector_performance import ConnectorPerformanceEvaluator

async def main():
    parser = argparse.ArgumentParser(description="Run a ResearchOS benchmark.")
    parser.add_argument("--dataset", required=True, help="Path to the YAML dataset file.")
    parser.add_argument("--output", default="benchmarks/results", help="Directory to store benchmark outputs.")
    
    args = parser.parse_args()
    
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {args.dataset}")
        sys.exit(1)
        
    dataset = load_dataset(dataset_path)
    
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting Benchmark Run: {run_id}")
    print(f"Dataset: {dataset.dataset_id} | Domain: {dataset.metadata.domain}")
    
    collector = BenchmarkCollector(run_id, output_dir)
    runner = BenchmarkRunner(run_id, collector)
    
    await runner.run(dataset)
    
    collector.archive()
    
    print("Running evaluators...")
    evaluators = [
        FindingRecallEvaluator(),
        ProcessRetentionEvaluator(),
        QueryDiversityEvaluator(),
        ResultDiversityEvaluator(),
        DeduplicationSavingsEvaluator(),
        ConnectorPerformanceEvaluator()
    ]
    
    reporter = BenchmarkReporter(run_id, output_dir)
    artifacts = collector.get_all()
    
    for evaluator in evaluators:
        print(f" - Evaluating {evaluator.name}...")
        result = await evaluator.evaluate(artifacts, dataset)
        reporter.add_result(evaluator.name, result)
        
    reporter.generate(dataset)
    print(f"Benchmark run {run_id} completed successfully.")
    print(f"Report available at {output_dir / run_id / 'benchmark_report.md'}")

if __name__ == "__main__":
    asyncio.run(main())

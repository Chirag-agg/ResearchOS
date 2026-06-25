from typing import List, Optional
from pydantic import BaseModel
import yaml
from pathlib import Path


class BenchmarkMetadata(BaseModel):
    difficulty: str
    expected_rounds: int
    expected_runtime: int
    expected_findings: int
    domain: str


class BenchmarkBackground(BaseModel):
    known_facts: List[str] = []
    common_knowledge: List[str] = []
    required_findings: List[str] = []
    stretch_findings: List[str] = []


class GroundTruthFinding(BaseModel):
    finding: str
    evidence: str
    source: str
    importance: int  # 1 to 5
    novelty: int     # 1 to 5


class BenchmarkDataset(BaseModel):
    dataset_id: str
    question: str
    metadata: BenchmarkMetadata
    background: BenchmarkBackground
    ground_truth: List[GroundTruthFinding]


def load_dataset(file_path: str | Path) -> BenchmarkDataset:
    """Load and validate a YAML benchmark dataset."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    path_obj = Path(file_path)
    if "dataset_id" not in data:
        data["dataset_id"] = f"{path_obj.parent.name}/{path_obj.stem}"
        
    return BenchmarkDataset(**data)

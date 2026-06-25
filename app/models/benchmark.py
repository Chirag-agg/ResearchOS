from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class BenchmarkRun(SQLModel, table=True):
    """
    Isolated from research OS DB. Represents a single execution of a benchmark suite.
    """
    __tablename__ = "benchmark_runs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Configuration Fingerprint
    commit: str = Field(default="unknown")
    branch: str = Field(default="unknown")
    corpus: str = Field(default="golden_v1")
    configuration_hash: str = Field(nullable=False, index=True)
    pipeline_fingerprint: str = Field(nullable=False, index=True)

class BenchmarkMetric(SQLModel, table=True):
    """
    Normalized metric storage to avoid schema migrations.
    """
    __tablename__ = "benchmark_metrics"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="benchmark_runs.id", ondelete="CASCADE", index=True)
    
    metric_name: str = Field(nullable=False, index=True)
    metric_value: float = Field(nullable=False)
    unit: str = Field(default="ratio")
    stage: str = Field(nullable=False, index=True)

class LatencySample(SQLModel, table=True):
    """
    Event-based raw latency storage.
    """
    __tablename__ = "latency_samples"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="benchmark_runs.id", ondelete="CASCADE", index=True)
    
    stage: str = Field(nullable=False, index=True)
    document_id: str = Field(nullable=False)
    duration_ms: float = Field(nullable=False)

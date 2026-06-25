import hashlib
from typing import List
from app.models.insight import Insight
from app.services.insight_pipeline.clusterer import FindingCluster

class InsightCanonicalizer:
    """
    Stage 4: Canonicalization
    Generates a canonical hash based on semantic identity, separate from support:
    sorted primary entities + research question hash + cluster type.
    """
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _compute_hash(self, cluster: FindingCluster, research_question: str) -> str:
        """
        Computes the semantic identity hash.
        """
        rq_hash = hashlib.sha256(research_question.encode('utf-8')).hexdigest()[:16]
        
        raw = f"{'|'.join(cluster.primary_entities)}::{rq_hash}::{cluster.cluster_type.value}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
        
    def canonicalize(self, insight: Insight, cluster: FindingCluster, research_question: str) -> Insight:
        """
        Canonicalizes a validated Insight.
        """
        insight.stable_hash = self._compute_hash(cluster, research_question)
        
        # Mock: DB lookup for existing insight by stable_hash
        existing_insight = None 
        # if exists, merge provenance:
        # existing_insight.supporting_findings.extend(new_findings)
        # return existing_insight
        
        return insight

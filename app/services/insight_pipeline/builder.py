import logging
from typing import List, Optional
from pydantic import BaseModel
from app.models.insight import Insight
from app.services.insight_pipeline.clusterer import FindingCluster

logger = logging.getLogger(__name__)

class CandidateInsight(BaseModel):
    text: str

class InsightBuilder:
    """
    Stage 2: Candidate Insight (LLM Stage)
    Prompt strictly constrained to "What broader conclusion follows from these findings?"
    Input ONLY: Research Question, Grouped Findings, Shared Entities, Contradictions.
    """
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        
    def _build_prompt(self, cluster: FindingCluster, research_question: str) -> str:
        """
        Builds the narrow LLM prompt.
        """
        finding_texts = "\n".join([f"- {f.title}: {f.summary}" for f in cluster.findings])
        
        contradictions = []
        for f in cluster.findings:
            if getattr(f, "contradicting_claims", None):
                contradictions.extend(f.contradicting_claims)
        contradiction_texts = "\n".join([f"- {c.predicate}" for c in contradictions])
        
        return f"""
        You are a strict research synthesizer.
        Your ONLY job is to discover the broader conclusion that follows from these synthesized Findings.
        
        Rules:
        1. DO NOT recommend actions or predict the future.
        2. DO NOT synthesize conclusions not backed by the provided Findings.
        
        Research Question: {research_question}
        Shared Entities: {cluster.primary_entities}
        
        Findings:
        {finding_texts}
        
        Contradictions Detected in Underlying Claims:
        {contradiction_texts if contradiction_texts else "None"}
        """

    async def build(self, cluster: FindingCluster, research_question: str) -> Optional[CandidateInsight]:
        """
        Calls the LLM and returns a CandidateInsight.
        (MOCK IMPLEMENTATION FOR NOW)
        """
        if not cluster.findings:
            return None
            
        # prompt = self._build_prompt(cluster, research_question)
        # Stub
        return CandidateInsight(
            text="Across evaluated benchmarks, GPT-4 consistently demonstrates superior performance over current open-weight alternatives."
        )

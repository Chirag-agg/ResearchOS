import logging
from typing import List, Optional
from pydantic import BaseModel
from app.models.finding import Finding
from app.services.finding_pipeline.grouper import ClaimGroup

logger = logging.getLogger(__name__)

class CandidateFinding(BaseModel):
    title: str
    summary: str

class FindingBuilder:
    """
    Stage 2: Candidate Finding (LLM Stage)
    Prompt strictly constrained to "What conclusion is directly supported by this group of claims?"
    """
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        
    def _build_prompt(self, group: ClaimGroup, research_question: str) -> str:
        """
        Builds the narrow LLM prompt.
        """
        claim_texts = "\n".join([f"- Subject: {c.subject_entity_id}, Predicate: {c.predicate}, Object: {c.object_entity_id}" for c in group.claims])
        
        return f"""
        You are a strict research synthesizer.
        Your ONLY job is to state the explicit conclusion directly supported by the following group of claims.
        
        Rules:
        1. DO NOT extrapolate or discuss implications.
        2. DO NOT synthesize conclusions not backed by the provided claims.
        3. DO NOT answer the overarching research question if the claims don't cover it.
        
        Research Question context: {research_question}
        
        Claims:
        {claim_texts}
        """

    async def build(self, group: ClaimGroup, research_question: str) -> Optional[CandidateFinding]:
        """
        Calls the LLM and returns a CandidateFinding.
        (MOCK IMPLEMENTATION FOR NOW)
        """
        if not group.claims:
            return None
            
        # prompt = self._build_prompt(group, research_question)
        # Stub
        return CandidateFinding(
            title="GPT-4 Benchmark Performance",
            summary="Multiple evaluations indicate GPT-4 outperforms Llama-3-70B and achieves over 94% accuracy on standard tasks."
        )

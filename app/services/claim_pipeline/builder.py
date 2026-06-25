from typing import List, Dict, Any
from app.models.claim import ClaimCandidate, ClaimPredicate
from app.models.observation import Observation
from app.models.evidence import Evidence

class ClaimBuilder:
    """
    Stage 1: Claim Builder
    Uses LLM to convert a canonical Observation and its Evidence into structured RDF Claims.
    """
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        
    def _build_prompt(self, observation: Observation, evidence: List[Evidence], local_context: str) -> str:
        """
        Builds the narrowly focused prompt.
        """
        valid_predicates = [p.value for p in ClaimPredicate]
        
        return f"""
        You are a strict knowledge extractor. 
        Your ONLY job is to convert the provided Observation into structured RDF relationships (Subject -> Predicate -> Object).
        
        Rules:
        1. You must ONLY extract relationships explicitly supported by the Observation and Evidence.
        2. The Predicate MUST be one of the following exact strings: {valid_predicates}
        3. Do NOT synthesize conclusions or answer questions about the paper.
        4. Provide a verbatim evidence_snippet from the provided Evidence.
        5. Provide a predicate_confidence score between 0.0 and 1.0.
        
        Observation: {observation.text}
        
        Evidence Excerpts:
        {[e.excerpt for e in evidence]}
        
        Context:
        {local_context}
        """

    async def build(self, observation: Observation, evidence: List[Evidence], local_context: str) -> List[ClaimCandidate]:
        """
        Calls the LLM and returns ClaimCandidates.
        (MOCK IMPLEMENTATION FOR NOW)
        """
        # prompt = self._build_prompt(observation, evidence, local_context)
        # In a real impl, we'd call self.llm_client and parse JSON into ClaimCandidate.
        
        # Stub for prototype:
        return [
            ClaimCandidate(
                subject="Model A",
                predicate=ClaimPredicate.ACHIEVES.value,
                object="94.6% accuracy",
                evidence_snippet="Model A achieved an accuracy of 94.6%",
                predicate_confidence=0.96
            )
        ]

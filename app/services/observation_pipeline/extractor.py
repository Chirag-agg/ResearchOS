import hashlib
import json
import logging
from typing import List
from datetime import datetime
from uuid import uuid4

from app.models.observation import CandidateObservation, ObservationKind, ObservationPolarity
from app.models.observation_context import ObservationContext, ObservationPrompt

logger = logging.getLogger(__name__)

class ObservationExtractorError(Exception):
    pass

class ObservationExtractor:
    """
    Compiler-style LLM frontend for Observation extraction.
    Only proposes Candidates. Never persists directly.
    """
    def __init__(self, llm_service, version: str = "1.0.0"):
        self.llm = llm_service
        self.version = version
        
        self.system_prompt = (
            "You are a strict, objective fact extractor. Your ONLY job is to extract factual observations "
            "from the provided text artifact.\n\n"
            "Rules:\n"
            "1. Answer EXACTLY 'What was observed?'. Never answer 'Why?' or 'How important?'.\n"
            "2. Extract facts belonging to one of the allowed kinds: METRIC, RESULT, DATASET, METHOD, etc.\n"
            "3. State the polarity: POSITIVE, NEGATIVE, NEUTRAL.\n"
            "4. Provide character-level offsets relative to the artifact text for EVERY observation.\n"
            "5. Return a JSON array of observations.\n"
        )

    def _build_prompt(self, context: ObservationContext) -> ObservationPrompt:
        variables = context.model_dump(mode="json")
        rendered = (
            f"Research Question: {context.research_question}\n"
            f"Section Type: {context.section_type}\n"
            f"Artifact Text:\n{context.current_artifact_text}\n\n"
            f"Neighboring Context (Previous): {context.previous_artifact_text or 'None'}\n"
            f"Neighboring Context (Next): {context.next_artifact_text or 'None'}\n"
            f"Document Summary: {context.document_summary}\n"
            f"Known Entities: {', '.join(context.known_entities) if context.known_entities else 'None'}\n"
        )
        
        template_hash = hashlib.sha256(self.system_prompt.encode()).hexdigest()
        
        return ObservationPrompt(
            version=self.version,
            template_hash=template_hash,
            variables=variables,
            rendered_prompt=rendered
        )

    async def extract(self, context: ObservationContext) -> List[CandidateObservation]:
        """
        Executes the prompt against the LLM to yield candidate observations.
        """
        prompt = self._build_prompt(context)
        
        try:
            # Here we would call self.llm.generate(...)
            # For now, we mock the response parsing
            # response = await self.llm.generate(system=self.system_prompt, user=prompt.rendered_prompt, format="json")
            # raw_candidates = json.loads(response)
            raw_candidates = [] # Mock empty for now
            
            candidates = []
            artifact_hash = hashlib.sha256(context.current_artifact_text.encode()).hexdigest()
            now = datetime.utcnow().isoformat()
            
            for raw in raw_candidates:
                candidate = CandidateObservation(
                    text=raw["text"],
                    kind=ObservationKind(raw["kind"]),
                    polarity=ObservationPolarity(raw.get("polarity", "NEUTRAL")),
                    extraction_confidence=raw.get("confidence", 1.0),
                    extraction_notes=raw.get("notes"),
                    evidence_offsets=raw.get("offsets", []),
                    supporting_sentences=raw.get("sentences", []),
                    prompt_hash=prompt.template_hash,
                    extractor_version=self.version,
                    artifact_hash=artifact_hash,
                    llm_model="mock-model", # Replace with actual
                    temperature=0.0,
                    created_at=now
                )
                candidates.append(candidate)
                
            return candidates
            
        except Exception as e:
            logger.error(f"Observation extraction failed: {e}")
            raise ObservationExtractorError(f"Failed to extract observations: {e}")

import hashlib
import logging
from typing import Optional
from app.models.observation import CandidateObservation, Observation
from app.services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)

class ObservationCanonicalizer:
    """
    Deduplicates and canonicalizes CandidateObservations.
    """
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _compute_stable_hash(self, candidate: CandidateObservation, document_id: str, location: str) -> str:
        """
        Computes the identity hash for synchronous deduplication.
        """
        normalized_text = TextNormalizer.normalize(candidate.text).lower()
        raw = f"{document_id}:{location}:{normalized_text}"
        return hashlib.sha256(raw.encode()).hexdigest()
        
    def canonicalize_sync(self, candidate: CandidateObservation, document_id: str, location: str) -> Observation:
        """
        Fast synchronous canonicalization using stable hash.
        Checks if exact observation exists for this document/location.
        """
        stable_hash = self._compute_stable_hash(candidate, document_id, location)
        
        # In a real implementation, we would query the DB for this stable_hash.
        # If exists, return it (and we will link the new Evidence to it).
        # Otherwise, construct a new Canonical Observation.
        
        return Observation(
            stable_hash=stable_hash,
            kind=candidate.kind,
            polarity=candidate.polarity,
            text=candidate.text,
            extraction_confidence=candidate.extraction_confidence,
            validator_notes=candidate.extraction_notes,
            # Document and session IDs would be mapped here
        )
        
    async def canonicalize_async(self):
        """
        Background worker stub for FAISS semantic merging.
        """
        pass

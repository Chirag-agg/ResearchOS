import logging
from typing import Tuple, Optional, List
from uuid import uuid4

from app.models.claim import ClaimCandidate, ClaimPredicate, Claim
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)

class ClaimValidator:
    """
    Stage 2: Deterministic Validator
    Strictly validates predicates, handles entity resolution, checks grounding,
    and computes overall confidence.
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _resolve_entity(self, entity_text: str) -> Tuple[str, float]:
        """
        Resolves an entity text to an Entity UUID.
        Resolution order: Exact match -> Alias -> Stable Hash -> Create.
        Returns (entity_id_str, entity_confidence).
        (Mocked for prototype)
        """
        normalized = TextNormalizer.normalize(entity_text)
        # Mock DB resolution
        # return ("resolved-uuid", 1.0)
        # If not found:
        # return ("new-uuid", 0.9)
        return (str(uuid4()), 0.95)

    def validate(self, candidate: ClaimCandidate, evidence: List[Evidence]) -> Tuple[bool, Optional[Claim], str]:
        """
        Validates the candidate.
        Returns (passed, Claim, rejection_reason).
        """
        # 1. Predicate Validation
        try:
            valid_predicate = ClaimPredicate(candidate.predicate)
        except ValueError:
            return False, None, f"Unknown predicate: {candidate.predicate}"
            
        # 2. Evidence Coverage
        if not evidence:
            return False, None, "Evidence missing"
            
        # Check if evidence snippet is roughly grounded in the actual evidence objects
        # (In a full implementation, run TextNormalizer and search)
        grounding_confidence = 1.0
        
        # 3. Entity Resolution
        subject_id, subj_conf = self._resolve_entity(candidate.subject)
        object_id, obj_conf = self._resolve_entity(candidate.object)
        
        if not subject_id or not object_id:
            return False, None, "Entity unresolved"
            
        entity_confidence = min(subj_conf, obj_conf)
        
        # 4. Confidence Computation (Fixed Weights)
        # 0.4 grounding + 0.35 entity + 0.25 predicate
        overall_conf = (0.4 * grounding_confidence) + (0.35 * entity_confidence) + (0.25 * candidate.predicate_confidence)
        
        # Construct Validated Claim (without stable hash yet)
        claim = Claim(
            session_id=uuid4(), # Mock
            subject_entity_id=subject_id,
            predicate=valid_predicate.value,
            object_entity_id=object_id,
            entity_confidence=entity_confidence,
            grounding_confidence=grounding_confidence,
            predicate_confidence=candidate.predicate_confidence,
            overall_confidence=overall_conf,
            stable_hash="placeholder"
        )
        
        return True, claim, "Valid"

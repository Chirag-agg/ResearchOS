import hashlib
from app.models.claim import Claim

class ClaimCanonicalizer:
    """
    Stage 3: Canonicalization
    Deduplicates claims using SHA256(Subject Entity ID + Predicate + Object Entity ID).
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _compute_hash(self, claim: Claim) -> str:
        """
        Computes the identity hash.
        Normalized entity IDs and predicate ensures true canonical identity.
        """
        raw = f"{claim.subject_entity_id}:{claim.predicate}:{claim.object_entity_id}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
        
    def canonicalize(self, claim: Claim) -> Claim:
        """
        Canonicalizes a validated Claim.
        """
        claim.stable_hash = self._compute_hash(claim)
        # Mock: DB lookup for existing claim by stable_hash
        # If exists, merge evidence references and return existing.
        # Otherwise, return new claim.
        return claim

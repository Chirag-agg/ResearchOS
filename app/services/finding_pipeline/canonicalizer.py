import hashlib
from typing import List
from app.models.finding import Finding
from app.models.claim import Claim

class FindingCanonicalizer:
    """
    Stage 4: Canonicalization
    Generates a canonical hash based on semantic identity:
    Normalized Subject Entities + Predicate Cluster + Normalized Object Entities + Question Hash.
    Merges provenance without changing the stable identity.
    """
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _compute_hash(self, finding: Finding, research_question: str) -> str:
        """
        Computes the semantic identity hash.
        """
        # Extract unique normalized subject/object entities and predicates from supporting claims
        subjects = sorted(list(set([str(c.subject_entity_id) for c in finding.supporting_claims])))
        objects = sorted(list(set([str(c.object_entity_id) for c in finding.supporting_claims if c.object_entity_id])))
        predicates = sorted(list(set([c.predicate for c in finding.supporting_claims])))
        
        rq_hash = hashlib.sha256(research_question.encode('utf-8')).hexdigest()[:16]
        
        raw = f"{'|'.join(subjects)}::{'|'.join(predicates)}::{'|'.join(objects)}::{rq_hash}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
        
    def canonicalize(self, finding: Finding, research_question: str) -> Finding:
        """
        Canonicalizes a validated Finding.
        """
        finding.stable_hash = self._compute_hash(finding, research_question)
        
        # Mock: DB lookup for existing finding by stable_hash
        existing_finding = None 
        # if exists, merge provenance:
        # existing_finding.supporting_claims.extend(new_claims)
        # existing_finding.supporting_documents.extend(new_docs)
        # return existing_finding
        
        return finding

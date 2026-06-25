import logging
from typing import Tuple, Optional, List
from uuid import uuid4

from app.models.finding import Finding
from app.models.claim import Claim
from app.services.finding_pipeline.builder import CandidateFinding
from app.services.finding_pipeline.grouper import ClaimGroup

logger = logging.getLogger(__name__)

class FindingValidator:
    """
    Stage 3: Finding Validator
    Validates minimum evidence coverage, computes cross-source support,
    flags contradictions, and computes derived scores.
    """
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _count_evidence(self, claims: List[Claim]) -> int:
        """
        Mock: Returns the number of distinct evidence objects supporting these claims.
        """
        # In a real impl, iterate over claim.evidence
        return len(claims) + 1 # Mock >1 evidence for prototype
        
    def _get_supporting_documents(self, claims: List[Claim]) -> List[str]:
        """
        Mock: Returns list of distinct document IDs backing these claims.
        """
        return ["doc1", "doc2"] if len(claims) > 1 else ["doc1"]

    def _get_supporting_domains(self, claims: List[Claim]) -> List[str]:
        """
        Mock: Returns list of distinct domains backing these claims.
        """
        return ["arxiv.org", "aclweb.org"] if len(claims) > 1 else ["arxiv.org"]

    def _detect_contradictions(self, claims: List[Claim]) -> List[Claim]:
        """
        Detects opposing predicates within the semantic neighborhood.
        e.g., OUTPERFORMS vs UNDERPERFORMS.
        Returns the subset of claims that contradict the majority finding.
        """
        contradictions = []
        # Mock logic
        for c in claims:
            if c.predicate == "CONTRADICTS":
                contradictions.append(c)
        return contradictions

    def validate(self, candidate: CandidateFinding, group: ClaimGroup) -> Tuple[bool, Optional[Finding], str]:
        """
        Validates the candidate finding and builds the rich Finding object.
        """
        claims = group.claims
        
        # 1. Minimum Evidence Rule:
        # (>=2 claims) OR (1 claim + >=2 evidence objects)
        num_evidence = self._count_evidence(claims)
        if len(claims) < 2 and num_evidence < 2:
            return False, None, "Insufficient evidence: requires >=2 claims or >=2 evidence objects"
            
        # 2. Cross-document support
        doc_ids = self._get_supporting_documents(claims)
        domain_ids = self._get_supporting_domains(claims)
        
        # 3. Contradiction Detection
        contradicting_claims = self._detect_contradictions(claims)
        supporting_claims = [c for c in claims if c not in contradicting_claims]
        
        # 4. Derived Scoring
        # confidence = average confidence of supporting claims
        if supporting_claims:
            avg_conf = sum(c.overall_confidence for c in supporting_claims) / len(supporting_claims)
        else:
            avg_conf = 0.0
            
        novelty_score = 0.5 # Would come from evaluator
        importance_score = 0.8 # Would come from question relevance
        
        finding = Finding(
            session_id=uuid4(), # Mock
            title=candidate.title,
            summary=candidate.summary,
            confidence_score=avg_conf,
            novelty_score=novelty_score,
            importance_score=importance_score,
            stable_hash="placeholder" # Handled by canonicalizer
        )
        
        # Attach relationships (Mocked list assignment)
        finding.supporting_claims = supporting_claims
        finding.contradicting_claims = contradicting_claims
        # finding.supporting_documents = ... 
        
        return True, finding, "Valid"

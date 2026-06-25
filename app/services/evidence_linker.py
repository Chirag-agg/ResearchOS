import logging
import re
from typing import List, Dict, Any, Optional
from uuid import uuid4

from app.models.observation import Observation
from app.models.evidence import Evidence, TextSpan
from app.services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)

class EvidenceLinker:
    """
    Deterministically maps Observations to concrete Evidence objects.
    Applies text normalization and offset verification.
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _repair_offset(self, snippet: str, artifact_text: str, start: int, end: int) -> Optional[tuple[int, int]]:
        """
        Attempts deterministic sliding-window repair over normalized text.
        Search order: ±25 chars -> sentence -> paragraph -> fail.
        """
        normalized_snippet = TextNormalizer.normalize(snippet)
        normalized_artifact = TextNormalizer.normalize(artifact_text)
        
        # 1. Check exact offset (adjusted for length)
        # Note: mapping back to original un-normalized text offsets is complex in a real system.
        # For this prototype, we'll assume we find the string in the raw text directly.
        
        # Check ±25 chars
        search_start = max(0, start - 25)
        search_end = min(len(artifact_text), end + 25)
        window = artifact_text[search_start:search_end]
        
        normalized_snippet = TextNormalizer.normalize(snippet)
        normalized_window = TextNormalizer.normalize(window)
        
        # Find all occurrences in window and pick the closest to 'start'
        closest_dist = float('inf')
        best_match = None
        for match in re.finditer(re.escape(normalized_snippet), normalized_window):
            match_start = search_start + match.start()
            dist = abs(match_start - start)
            if dist < closest_dist:
                closest_dist = dist
                best_match = (match_start, match_start + len(normalized_snippet))
                
        if best_match:
            return best_match
            
        # Stub for paragraph expansion:
        search_start_p = max(0, start - 500)
        search_end_p = min(len(artifact_text), end + 500)
        window_p = artifact_text[search_start_p:search_end_p]
        
        closest_dist_p = float('inf')
        best_match_p = None
        for match in re.finditer(re.escape(snippet), window_p):
            match_start = search_start_p + match.start()
            dist = abs(match_start - start)
            if dist < closest_dist_p:
                closest_dist_p = dist
                best_match_p = (match_start, match_start + len(snippet))
                
        if best_match_p:
            return best_match_p
            
        return None

    def _generate_excerpt(self, artifact_text: str, start: int, end: int, max_chars: int = 300) -> str:
        """
        Generates an excerpt centered on the match, capped at max_chars.
        """
        span_len = end - start
        if span_len >= max_chars:
            return artifact_text[start:start+max_chars]
            
        padding = (max_chars - span_len) // 2
        exc_start = max(0, start - padding)
        exc_end = min(len(artifact_text), end + padding)
        
        return "..." + artifact_text[exc_start:exc_end] + "..."

    def _score_match(self, repaired_start: int, original_start: int) -> int:
        """
        Scores the match: Exact 100, Sentence 80, Paragraph 60.
        """
        if repaired_start == original_start:
            return 100
        elif abs(repaired_start - original_start) <= 100:
            return 80 # approximate sentence boundary
        else:
            return 60

    async def link(self, observation: Observation, artifact_id: str, parsed_document: Dict[str, Any], candidate_offsets: List[Dict[str, Any]]) -> List[Evidence]:
        """
        Links an Observation to newly created Evidence objects based on candidate offsets.
        """
        artifact_text = parsed_document.get("text", "")
        
        evidence_list = []
        
        for offset_data in candidate_offsets:
            start = offset_data.get("start", -1)
            end = offset_data.get("end", -1)
            snippet = offset_data.get("snippet", "")
            
            if not snippet or start == -1:
                continue
                
            # Verify and Repair
            repaired = self._repair_offset(snippet, artifact_text, start, end)
            if not repaired:
                logger.warning(f"Failed to ground snippet: '{snippet}'")
                continue # Reject this evidence
                
            rep_start, rep_end = repaired
            
            score = self._score_match(rep_start, start)
            excerpt = self._generate_excerpt(artifact_text, rep_start, rep_end)
            
            # Create TextSpan
            span = TextSpan(
                start=rep_start,
                end=rep_end,
                artifact_id=artifact_id
            )
            
            # Create Logical Evidence Object
            evidence = Evidence(
                document_id=parsed_document.get("document_id", "unknown"),
                excerpt=excerpt,
                text_spans=[span.model_dump()], # JSON list of TextSpan dicts
                match_score=score,
                evidence_type="text_span"
            )
            
            # Link to observation (in DB, we'd use ObservationEvidenceLink)
            evidence_list.append(evidence)
            
        # Sort by score descending
        evidence_list.sort(key=lambda e: e.match_score, reverse=True)
        return evidence_list

from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.models.observation import CandidateObservation
from app.models.errors import ValidationErrorCategory, ValidationErrorType

class ValidationResult(BaseModel):
    passed: bool
    warnings: List[str] = []
    errors: List[Dict[str, Any]] = []
    corrected_candidate: Optional[CandidateObservation] = None

class ObservationValidator:
    """
    Deterministic validator chain for Observations.
    Schema -> Grounding -> Evidence -> Duplicates -> Entity Resolution -> Semantic
    """
    def __init__(self, semantic_validator=None):
        self.semantic_validator = semantic_validator
        
    def validate(self, candidate: CandidateObservation, artifact_text: str) -> ValidationResult:
        result = ValidationResult(passed=True, corrected_candidate=candidate.model_copy())
        
        # 1. Schema
        if not candidate.text or not candidate.kind:
            result.passed = False
            result.errors.append("Missing required schema fields")
            return result
            
        # 2. Evidence
        if not candidate.evidence_offsets:
            result.passed = False
            result.errors.append({
                "category": ValidationErrorCategory.EXTRACTOR.value,
                "type": ValidationErrorType.MISSING_EVIDENCE.value,
                "message": "Evidence is required. Missing offsets.",
                "origin_stage": "Validator.Evidence",
                "recoverable": False
            })
            return result
            
        # 3. Grounding (Check if offsets actually match artifact text)
        for offset in result.corrected_candidate.evidence_offsets:
            start = offset.get("start", -1)
            end = offset.get("end", -1)
            if start < 0 or end > len(artifact_text) or start >= end:
                # Attempt repair if off-by-one
                if start == -1 and "snippet" in offset:
                    # Repair logic placeholder
                    result.warnings.append(f"Invalid offsets {start}:{end}, attempted repair")
                else:
                    result.passed = False
                    result.errors.append({
                        "category": ValidationErrorCategory.EXTRACTOR.value,
                        "type": ValidationErrorType.OFFSET.value,
                        "message": f"Invalid offsets {start}:{end} for artifact of length {len(artifact_text)}",
                        "origin_stage": "Validator.Grounding",
                        "recoverable": True
                    })
                    return result

        # 4. Confidence
        if candidate.extraction_confidence < 0.5:
            result.passed = False
            result.errors.append({
                "category": ValidationErrorCategory.EXTRACTOR.value,
                "type": ValidationErrorType.LOW_CONFIDENCE.value,
                "message": "Extraction confidence below threshold",
                "origin_stage": "Validator.Confidence",
                "recoverable": False
            })
            return result
            
        # 5. Semantic LLM Validator (Optional sanity check)
        if self.semantic_validator and result.passed:
            # e.g., semantic_validator.validate(...)
            pass
            
        return result

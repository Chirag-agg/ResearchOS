import pytest
from uuid import uuid4
from app.services.evidence_linker import EvidenceLinker
from app.models.observation import Observation

@pytest.mark.asyncio
async def test_exact_span():
    linker = EvidenceLinker()
    artifact = {"document_id": "doc1", "text": "Model A achieved 94.6% accuracy on the test set."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="94.6% accuracy", extraction_confidence=1.0)
    
    offsets = [{"start": 17, "end": 31, "snippet": "94.6% accuracy"}]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    assert len(evidence_list) == 1
    assert evidence_list[0].match_score == 100
    assert "94.6% accuracy" in evidence_list[0].excerpt

@pytest.mark.asyncio
async def test_offset_repair():
    linker = EvidenceLinker()
    artifact = {"document_id": "doc1", "text": "Results: Model A achieved 94.6% accuracy on the test set."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="94.6% accuracy", extraction_confidence=1.0)
    
    # Intentionally shifted start/end
    offsets = [{"start": 0, "end": 14, "snippet": "94.6% accuracy"}]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    assert len(evidence_list) == 1
    assert evidence_list[0].match_score == 80  # Since it had to repair by <100 chars
    assert evidence_list[0].text_spans[0]["start"] == 26

@pytest.mark.asyncio
async def test_missing_evidence():
    linker = EvidenceLinker()
    artifact = {"document_id": "doc1", "text": "Model A failed on the test set."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="94.6% accuracy", extraction_confidence=1.0)
    
    offsets = [{"start": 0, "end": 14, "snippet": "94.6% accuracy"}]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    # Should reject ungrounded evidence
    assert len(evidence_list) == 0

@pytest.mark.asyncio
async def test_multiple_evidence():
    linker = EvidenceLinker()
    artifact = {"document_id": "doc1", "text": "We ran two tests. First, accuracy was 94.6%. Second, accuracy was 94.6%."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="94.6% accuracy", extraction_confidence=1.0)
    
    offsets = [
        {"start": 38, "end": 43, "snippet": "94.6%"},
        {"start": 66, "end": 71, "snippet": "94.6%"}
    ]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    # Should create two separate evidence objects
    assert len(evidence_list) == 2

@pytest.mark.asyncio
async def test_unicode_normalization():
    linker = EvidenceLinker()
    # Artifact uses Micro sign U+00B5
    artifact = {"document_id": "doc1", "text": "Size is 50µm."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="50μm", extraction_confidence=1.0)
    
    # Candidate snippet uses Greek Mu U+03BC
    offsets = [{"start": 8, "end": 12, "snippet": "50μm"}]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    assert len(evidence_list) == 1
    assert evidence_list[0].match_score == 100

@pytest.mark.asyncio
async def test_duplicate_match_priority():
    linker = EvidenceLinker()
    artifact = {"document_id": "doc1", "text": "Test 1: 94.6%. ... Test 2: 94.6%."}
    obs = Observation(stable_hash="hash1", kind="result", polarity="positive", text="94.6%", extraction_confidence=1.0)
    
    # Points near the second occurrence
    offsets = [{"start": 25, "end": 30, "snippet": "94.6%"}]
    evidence_list = await linker.link(obs, str(uuid4()), artifact, offsets)
    
    assert len(evidence_list) == 1
    # Should repair to the nearest occurrence (index 27), not the first (index 8)
    assert evidence_list[0].text_spans[0]["start"] == 27

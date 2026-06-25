import logging
from typing import List, Dict
from app.models.finding import Finding
from app.models.insight import InsightType

logger = logging.getLogger(__name__)

class FindingCluster:
    """
    A cluster of related findings.
    """
    def __init__(self, primary_entities: List[str], cluster_type: InsightType):
        self.primary_entities = sorted(primary_entities)
        self.cluster_type = cluster_type
        self.findings: List[Finding] = []
        
    def add_finding(self, finding: Finding):
        self.findings.append(finding)

class FindingClusterer:
    """
    Stage 1: Finding Clusterer
    Deterministically clusters findings based on shared entities and concepts.
    """
    def __init__(self, db_session=None):
        self.db = db_session
        
    def _extract_primary_entities(self, finding: Finding) -> List[str]:
        """
        Mock: Extracts the core entities driving the finding.
        """
        entities = set()
        for c in finding.supporting_claims:
            entities.add(str(c.subject_entity_id))
            if c.object_entity_id:
                entities.add(str(c.object_entity_id))
        return list(entities)

    def cluster_findings(self, findings: List[Finding]) -> List[FindingCluster]:
        """
        Groups findings deterministically.
        """
        clusters: Dict[str, FindingCluster] = {}
        
        for finding in findings:
            entities = self._extract_primary_entities(finding)
            key = "::".join(sorted(entities))
            
            # Mock assigning to CONSENSUS
            if key not in clusters:
                clusters[key] = FindingCluster(entities, InsightType.CONSENSUS)
            
            clusters[key].add_finding(finding)
            
        return list(clusters.values())

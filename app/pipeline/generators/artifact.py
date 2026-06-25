import time
import re
from typing import List, Tuple, Dict, Any
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext
from app.pipeline.ir import DocumentNode, SectionNode, SectionRole, TableNode, ParagraphNode, HeadingNode
from app.models.document import DocumentArtifact, EntityMention

class ArtifactGeneratorStage(PipelineStage[DocumentNode, List[DocumentArtifact]]):
    """
    Transforms the frozen IR tree into rich DocumentArtifacts for database persistence.
    Computes local feature vectors (math, entities, metrics) for each artifact.
    """
    name = "ArtifactGeneratorStage"
    version = "1.0.0"

    def _extract_features(self, text: str) -> Dict[str, Any]:
        """Compute structural/semantic feature vector for a text block."""
        f = {
            "struct_contains_math": False,
            "struct_contains_table": False,
            "struct_contains_equation": False,
            "struct_contains_reference": False,
            "sem_contains_metric": False,
            "sem_contains_dataset": False,
            "sem_contains_code": False,
            "stat_sentence_count": len(re.split(r'[.!?]+', text)) - 1 if text else 0,
            "stat_citation_density": 0.0,
            "stat_numeric_density": 0.0,
            "stat_importance_score": 0.5
        }
        
        # Simple heuristics
        if re.search(r'\b(eq|equation|math)\b', text.lower()) or "=" in text:
            f["struct_contains_math"] = True
        if re.search(r'\b\d+(\.\d+)?(%)?\b', text):
            f["sem_contains_metric"] = True
        if re.search(r'\[\d+(?:,\s*\d+)*\]', text):
            f["struct_contains_reference"] = True
            f["stat_citation_density"] = len(re.findall(r'\[\d+\]', text)) / max(1, f["stat_sentence_count"])
            
        return f
        
    def _extract_entities(self, text: str) -> List[str]:
        """Simple deterministic exact-match entity extraction for demonstration."""
        # A real system uses SpaCy or a specific dictionary linker.
        known_entities = ["GPT-4", "ImageNet", "BLEU", "ResNet", "Nature", "ICLR"]
        found = []
        for e in known_entities:
            if e in text:
                found.append(e)
        return found

    async def process(self, root: DocumentNode, context: PipelineContext) -> StageResult[List[DocumentArtifact]]:
        start_time = time.time()
        
        artifacts = []
        global_index = 0
        
        def traverse(node: DocumentNode, current_role: SectionRole):
            nonlocal global_index
            
            # Context inheritance
            role = current_role
            if isinstance(node, SectionNode):
                role = node.classification.role
                
            # If it's a leaf content node we care about
            if isinstance(node, (ParagraphNode, HeadingNode, TableNode)):
                # We extract the content
                content = node.text if not isinstance(node, TableNode) else "TABLE_CONTENT_PLACEHOLDER"
                if content:
                    features = self._extract_features(content)
                    
                    artifact = DocumentArtifact(
                        artifact_type=node.node_type,
                        content=content,
                        section_role=role,
                        sequence_index=global_index,
                        **features
                    )
                    
                    # Early Entity Extraction
                    entities = self._extract_entities(content)
                    for e in entities:
                        # Append directly to the artifact's relationship list
                        artifact.entity_mentions.append(EntityMention(mention_text=e))
                        
                    artifacts.append(artifact)
                    global_index += 1
                    
            # Recurse
            for child in node.children:
                traverse(child, role)
                
        traverse(root, SectionRole.UNKNOWN)
        
        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=artifacts,
            metrics={"artifacts_generated": len(artifacts)},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

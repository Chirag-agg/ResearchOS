import time
from typing import List, Tuple
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext
from app.pipeline.ir import (
    DocumentNode, SectionNode, HeadingNode, SectionRole, 
    SectionClassification, generate_deterministic_id
)

class SectionClassifierStage(PipelineStage[DocumentNode, DocumentNode]):
    """
    Sweeps the IR tree, groups nodes following a HeadingNode into a SectionNode,
    and applies heuristic SectionClassification (Role, Confidence, Evidence).
    Returns a new immutable IR tree (IR v2).
    """
    name = "SectionClassifierStage"
    version = "1.0.0"

    def _classify_heading(self, text: str) -> SectionClassification:
        t = text.lower()
        role = SectionRole.UNKNOWN
        evidence = [f"Heading='{text}'"]
        confidence = 1.0
        
        if "abstract" in t:
            role = SectionRole.ABSTRACT
        elif "introduction" in t:
            role = SectionRole.INTRODUCTION
        elif "background" in t or "related work" in t or "prior work" in t or "literature" in t:
            role = SectionRole.BACKGROUND if "background" in t else SectionRole.RELATED_WORK
        elif "method" in t or "approach" in t or "architecture" in t:
            role = SectionRole.METHODS
        elif "experiment" in t or "evaluation" in t or "setup" in t:
            role = SectionRole.EXPERIMENTS
        elif "result" in t or "finding" in t:
            role = SectionRole.RESULTS
        elif "discussion" in t:
            role = SectionRole.DISCUSSION
        elif "limitation" in t:
            role = SectionRole.LIMITATIONS
        elif "future" in t:
            role = SectionRole.FUTURE_WORK
        elif "conclusion" in t or "concluding" in t:
            role = SectionRole.CONCLUSION
        elif "appendix" in t:
            role = SectionRole.APPENDIX
        elif "reference" in t or "bibliography" in t:
            role = SectionRole.REFERENCES
        elif "acknowledgement" in t or "acknowledgment" in t:
            role = SectionRole.ACKNOWLEDGEMENTS
        else:
            confidence = 0.5
            
        return SectionClassification(
            role=role,
            confidence=confidence,
            classifier="heuristic_v1",
            evidence=evidence
        )

    def _group_into_sections(self, nodes: List[DocumentNode], doc_fingerprint: str) -> List[DocumentNode]:
        """
        Takes a flat list of nodes, finds Headings, and wraps the heading + subsequent siblings 
        into a SectionNode until a heading of equal or higher level is encountered.
        """
        if not nodes:
            return []
            
        result = []
        i = 0
        while i < len(nodes):
            current = nodes[i]
            
            if isinstance(current, HeadingNode):
                # Start a new section
                section_children = [current] # Heading goes inside the section too
                level = current.level
                j = i + 1
                
                # Consume siblings until next heading of equal or higher importance (lower level number)
                while j < len(nodes):
                    sibling = nodes[j]
                    if isinstance(sibling, HeadingNode) and sibling.level <= level:
                        break
                    section_children.append(sibling)
                    j += 1
                
                # Recursive group children if there are sub-headings?
                # Actually, standard AST grouping usually recurses. For MVP, we just do flat grouping or recurse.
                # Let's recurse inside the section to handle sub-sections
                nested_children = self._group_into_sections(section_children[1:], doc_fingerprint)
                final_children = [current] + nested_children
                
                classification = self._classify_heading(current.text)
                
                # We need a stable ID for the SectionNode. 
                section_id = generate_deterministic_id(doc_fingerprint, f"section/{current.id}", current.text)
                
                sec_node = SectionNode(
                    id=section_id,
                    title=current.text,
                    classification=classification,
                    children=final_children,
                    provenance=current.provenance # inherit provenance from the heading
                )
                result.append(sec_node)
                i = j
            else:
                # Top level node not under any heading (e.g., title, authors before abstract)
                # Recurse its children if it's a container (e.g. div)
                if current.children:
                    updated_children = self._group_into_sections(current.children, doc_fingerprint)
                    current = current.model_copy(update={"children": updated_children})
                result.append(current)
                i += 1
                
        return result

    async def process(self, root: DocumentNode, context: PipelineContext) -> StageResult[DocumentNode]:
        start_time = time.time()
        
        # In a real system, the fingerprint is passed in context or stored on DocumentNode.
        # We will use "v2-section" for ID deterministic generation.
        doc_fingerprint = "v2-section"
        
        # The root node children are grouped into sections
        grouped_children = self._group_into_sections(root.children, doc_fingerprint)
        
        # Create IR v2 (immutable copy with new children)
        new_root = root.model_copy(update={"children": grouped_children})

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=new_root,
            metrics={"sections_created": len([c for c in grouped_children if isinstance(c, SectionNode)])},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

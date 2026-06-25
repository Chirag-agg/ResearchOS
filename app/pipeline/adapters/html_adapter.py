from bs4 import BeautifulSoup, Tag, NavigableString
import time
from typing import List
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext
from app.pipeline.ir import (
    DocumentNode, ParagraphNode, HeadingNode, TableNode, TableRowNode, 
    TableCellNode, FigureNode, EquationNode, CodeNode, ReferenceNode, 
    ListNode, ListItemNode, SectionNode, NodeOffsets, ProvenanceMetadata,
    generate_deterministic_id, SourceDocument
)

class HTMLAdapter(PipelineStage[SourceDocument, DocumentNode]):
    """
    Transforms raw HTML SourceDocument into the DocumentNode IR Tree.
    This acts as the DOM Builder.
    """
    name = "HTMLAdapter"
    version = "1.0.0"

    async def process(self, input_doc: SourceDocument, context: PipelineContext) -> StageResult[DocumentNode]:
        start_time = time.time()
        
        # Parse the raw content (which should be clean HTML)
        html_str = input_doc.raw_content.decode("utf-8")
        soup = BeautifulSoup(html_str, "lxml")
        
        # We will build a dummy fingerprint for ID generation since full fingerprinting
        # happens downstream or recursively. We use a placeholder for now.
        doc_fingerprint = "v1-html-adapter"
        
        root_node = DocumentNode(
            id=generate_deterministic_id(doc_fingerprint, "/html", ""),
            node_type="DOCUMENT",
            provenance=ProvenanceMetadata(source_tag="html", source_xpath="/html", parser_stage=self.name)
        )
        
        # Recursive builder
        def build_node(bs_node, xpath_prefix: str) -> DocumentNode:
            if isinstance(bs_node, NavigableString):
                text = str(bs_node).strip()
                if not text:
                    return None
                return ParagraphNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, text[:20]),
                    text=text,
                    provenance=ProvenanceMetadata(source_tag="text", source_xpath=xpath_prefix, parser_stage=self.name)
                )
                
            tag_name = bs_node.name.lower() if bs_node.name else "unknown"
            
            # Simple mappings
            if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(tag_name[1])
                text = bs_node.get_text(strip=True)
                return HeadingNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, text[:20]),
                    text=text,
                    level=level,
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            elif tag_name == "p":
                text = bs_node.get_text(strip=True)
                return ParagraphNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, text[:20]),
                    text=text,
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            elif tag_name == "table":
                # For brevity, standard TableNode instantiation
                # A real adapter maps children specifically to rows/cells
                return TableNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, "table"),
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            elif tag_name == "figure":
                return FigureNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, "figure"),
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            elif tag_name == "math":
                return EquationNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, "math"),
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            elif tag_name == "pre" or tag_name == "code":
                text = bs_node.get_text()
                return CodeNode(
                    id=generate_deterministic_id(doc_fingerprint, xpath_prefix, text[:20]),
                    text=text,
                    provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
                )
            
            # Default fallback for containers
            text = bs_node.get_text(strip=True)
            node = DocumentNode(
                id=generate_deterministic_id(doc_fingerprint, xpath_prefix, text[:20] if text else ""),
                text=text,
                provenance=ProvenanceMetadata(source_tag=tag_name, source_xpath=xpath_prefix, parser_stage=self.name)
            )
            
            # Recurse children
            children = []
            for i, child in enumerate(bs_node.children):
                child_node = build_node(child, f"{xpath_prefix}/{tag_name}[{i}]")
                if child_node:
                    children.append(child_node)
                    
            if children:
                # Need to explicitly set the list bypassing Pydantic validation 
                # (or since we use `model_copy` with `update` if frozen=True)
                node = node.model_copy(update={"children": children})
                
            return node
            
        
        body = soup.find("body") or soup
        ir_children = []
        for i, child in enumerate(body.children):
            c_node = build_node(child, f"/html/body[{i}]")
            if c_node:
                ir_children.append(c_node)
                
        root_node = root_node.model_copy(update={"children": ir_children})

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=root_node,
            metrics={"nodes_recovered": len(ir_children)}, # simplistic
            version=self.version,
            execution_time_ms=execution_time_ms
        )

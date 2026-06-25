import time
from typing import Dict, Any, List
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext
from app.pipeline.ir import DocumentNode, TableNode, TableRowNode, TableCellNode, HeadingNode, ParagraphNode

class StructuralValidationStage(PipelineStage[DocumentNode, DocumentNode]):
    """
    Validates the Document IR tree invariants and computes Structural Integrity.
    """
    name = "StructuralValidationStage"
    version = "1.0.0"

    async def process(self, root: DocumentNode, context: PipelineContext) -> StageResult[DocumentNode]:
        start_time = time.time()
        
        errors = []
        warnings = []
        stats = {
            "total_nodes": 0,
            "tables": 0,
            "headings": 0,
            "paragraphs": 0,
            "references": 0,
            "figures": 0,
            "equations": 0
        }
        
        def validate_node(node: DocumentNode, parent: DocumentNode = None):
            stats["total_nodes"] += 1
            node_type = node.node_type
            
            if node_type == "HEADING":
                stats["headings"] += 1
                if parent and parent.node_type == "HEADING":
                    errors.append(f"Heading {node.id} nested inside another heading.")
            elif node_type == "PARAGRAPH":
                stats["paragraphs"] += 1
            elif node_type == "TABLE":
                stats["tables"] += 1
            elif node_type == "TABLE_ROW":
                if parent is None or parent.node_type != "TABLE":
                    errors.append(f"TableRow {node.id} is not a direct child of a TABLE.")
            elif node_type == "TABLE_CELL":
                if parent is None or parent.node_type != "TABLE_ROW":
                    errors.append(f"TableCell {node.id} is not a direct child of a TABLE_ROW.")
            elif node_type == "FIGURE":
                stats["figures"] += 1
            elif node_type == "REFERENCE":
                stats["references"] += 1
            elif node_type == "EQUATION":
                stats["equations"] += 1
                
            for child in node.children:
                validate_node(child, node)
                
        validate_node(root)
        
        if root.node_type != "DOCUMENT":
            errors.append(f"Root node must be DOCUMENT, got {root.node_type}")
            
        # Simplified composite metric for Structural Integrity
        # Assumes ideal documents have at least some headings and paragraphs
        integrity_score = 1.0
        if stats["headings"] == 0:
            warnings.append("Document has no headings. Missing hierarchy.")
            integrity_score *= 0.8
        if stats["paragraphs"] == 0:
            errors.append("Document has no paragraphs. Likely parsing failure.")
            integrity_score *= 0.2
            
        if len(errors) > 0:
            status = StageStatus.SUCCESS_WITH_WARNINGS # For MVP we let it pass but flag it
        else:
            status = StageStatus.SUCCESS

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=status,
            output=root, # Immutable, passes through as-is if no recovery performed
            metrics={"structural_integrity": integrity_score, **stats},
            warnings=warnings,
            errors=errors,
            version=self.version,
            execution_time_ms=execution_time_ms
        )

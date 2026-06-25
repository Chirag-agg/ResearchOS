import time
from typing import Dict, Any
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext
from app.pipeline.ir import DocumentNode

class VisualizerStage(PipelineStage[DocumentNode, str]):
    """
    Consumes an IR tree and generates a colored, annotated document_ir.html
    for visual debugging of structural integrity, offsets, and node properties.
    """
    name = "VisualizerStage"
    version = "1.0.0"

    async def process(self, root: DocumentNode, context: PipelineContext) -> StageResult[str]:
        start_time = time.time()
        
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><title>Document IR Visual Debugger</title>",
            "<style>",
            "body { font-family: sans-serif; margin: 20px; background: #1e1e1e; color: #d4d4d4; }",
            ".node { border-left: 2px solid #555; margin-left: 20px; padding: 5px 0 5px 10px; }",
            ".node-type { font-weight: bold; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }",
            ".DOCUMENT { color: #569cd6; border-left: 2px solid #569cd6; }",
            ".HEADING { color: #c586c0; border-left: 2px solid #c586c0; }",
            ".PARAGRAPH { color: #ce9178; border-left: 2px solid #ce9178; }",
            ".TABLE { color: #4ec9b0; border-left: 2px solid #4ec9b0; }",
            ".TABLE_ROW { color: #4ec9b0; border-left: 2px solid #4ec9b0; }",
            ".TABLE_CELL { color: #4ec9b0; border-left: 2px solid #4ec9b0; }",
            ".FIGURE { color: #dcdcaa; border-left: 2px solid #dcdcaa; }",
            ".EQUATION { color: #9cdcfe; border-left: 2px solid #9cdcfe; }",
            ".meta { color: #808080; font-size: 0.8em; margin-left: 10px; }",
            ".text-content { margin-top: 5px; font-family: monospace; color: #a9b7c6; background: #2b2b2b; padding: 5px; }",
            "</style>",
            "</head><body>",
            "<h1>Document IR Tree</h1>"
        ]
        
        def render_node(node: DocumentNode):
            node_type = node.node_type
            html_parts.append(f'<div class="node {node_type}">')
            html_parts.append(f'<span class="node-type">{node_type}</span>')
            
            # Metadata
            meta_parts = []
            if getattr(node, "level", None):
                meta_parts.append(f"Level: {node.level}")
            if node.provenance.source_tag:
                meta_parts.append(f"&lt;{node.provenance.source_tag}&gt;")
            if node.provenance.source_xpath:
                meta_parts.append(f"XPath: {node.provenance.source_xpath}")
            if meta_parts:
                html_parts.append(f'<span class="meta">{" | ".join(meta_parts)}</span>')
                
            # Text Content
            if node.text:
                preview = node.text if len(node.text) < 150 else node.text[:150] + "..."
                html_parts.append(f'<div class="text-content">{preview}</div>')
                
            for child in node.children:
                render_node(child)
                
            html_parts.append('</div>')
            
        render_node(root)
        html_parts.append("</body></html>")
        
        output_html = "\n".join(html_parts)
        
        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=output_html,
            metrics={"nodes_rendered": len(output_html)},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

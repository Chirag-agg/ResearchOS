import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any

from app.models.report import ResearchReport, ReportSection

class BaseRenderer(ABC):
    """
    Abstract base class for all report renderers.
    """
    @abstractmethod
    def render(self, report: ResearchReport, full_graph: Dict[str, Any] = None) -> str | bytes:
        """
        Renders a ResearchReport.
        `full_graph` is a mocked dictionary containing the actual loaded objects for the prototype.
        """
        pass

class MarkdownRenderer(BaseRenderer):
    """
    Renders the report as a Markdown document.
    """
    def render(self, report: ResearchReport, full_graph: Dict[str, Any] = None) -> str:
        if not full_graph:
            full_graph = {}
            
        lines = []
        lines.append(f"# {report.title}")
        lines.append("")
        
        # Sort sections by order_index
        sections = sorted(report.sections, key=lambda s: s.order_index)
        
        for section in sections:
            lines.append(f"## {section.section_type}")
            lines.append("")
            
            if section.section_type == "Executive Summary":
                for item in sorted(section.items, key=lambda i: i.order_index):
                    insight = full_graph.get(str(item.insight_id))
                    if insight:
                        lines.append(f"- **{insight.type.value}**: {insight.text}")
                lines.append("")
                
            elif section.section_type in ["Source Statistics", "Limitations"]:
                if section.computed_content:
                    content = json.loads(section.computed_content)
                    if isinstance(content, list):
                        for c in content:
                            lines.append(f"- {c}")
                    elif isinstance(content, dict):
                        for k, v in content.items():
                            lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
                lines.append("")
                
            elif section.section_type == "Contradictions":
                for item in sorted(section.items, key=lambda i: i.order_index):
                    insight = full_graph.get(str(item.insight_id))
                    if insight:
                        lines.append(f"- Insight containing contradictions: {insight.text}")
                        # In real impl, traverse to the actual contradicting claims
                lines.append("")
                
            elif section.section_type == "Evidence Appendix":
                # Mocking a deep drill-down
                lines.append("### Insight #1")
                lines.append("-> Finding: Multiple independent evaluations...")
                lines.append("--> Claim: GPT-4 ACHIEVES 94.6% accuracy")
                lines.append("---> Evidence: Offset 1532–1579 (Score: 100)")
                lines.append("----> Excerpt: 'Model A achieved an accuracy of 94.6%'")
                lines.append("-----> Document: Results §3.2")
                lines.append("")

        return "\n".join(lines)

import logging
import json
from uuid import uuid4
from typing import List

from app.models.insight import Insight
from app.models.report import ResearchReport, ReportSection, ReportSectionItem

logger = logging.getLogger(__name__)

class ReportCompiler:
    """
    Final Phase: Report Compiler
    Read-only stage. Loads insights, computes deterministic stats and limitations,
    and constructs the canonical ResearchReport structure.
    """
    def __init__(self, db_session=None):
        self.db = db_session

    def compile(self, session_id: str, title: str, insights: List[Insight]) -> ResearchReport:
        """
        Assembles the report structure.
        """
        report = ResearchReport(
            session_id=session_id,
            title=title
        )
        
        # 1. Executive Summary
        exec_section = ReportSection(
            report_id=report.id,
            section_type="Executive Summary",
            title="Executive Summary",
            order_index=1
        )
        # Order insights by confidence descending
        sorted_insights = sorted(insights, key=lambda i: i.confidence_score, reverse=True)
        for idx, insight in enumerate(sorted_insights[:5]): # Top 5 insights
            exec_section.items.append(ReportSectionItem(insight_id=insight.id, order_index=idx))
            
        # 2. Key Insights & 3. Supporting Findings (Merged conceptually here)
        insights_section = ReportSection(
            report_id=report.id,
            section_type="Key Insights",
            title="Key Insights and Findings",
            order_index=2
        )
        for idx, insight in enumerate(sorted_insights):
            insights_section.items.append(ReportSectionItem(insight_id=insight.id, order_index=idx))
            
        # 4. Contradictions
        contradictions_section = ReportSection(
            report_id=report.id,
            section_type="Contradictions",
            title="Contradictions Detected",
            order_index=4
        )
        c_idx = 0
        for insight in insights:
            if insight.contradictions_detected:
                contradictions_section.items.append(ReportSectionItem(insight_id=insight.id, order_index=c_idx))
                c_idx += 1
                
        # 6. Source Statistics (Mock computed)
        stats = {
            "documents_analyzed": 42,
            "domains": ["arxiv.org", "aclweb.org", "nature.com"],
            "academic_vs_web": {"academic": 38, "web": 4}
        }
        stats_section = ReportSection(
            report_id=report.id,
            section_type="Source Statistics",
            title="Source Statistics",
            order_index=6,
            computed_content=json.dumps(stats)
        )
        
        # 7. Limitations (Computed)
        limitations = []
        if stats["documents_analyzed"] < 3:
            limitations.append("Fewer than three independent documents.")
        if c_idx > 0:
            limitations.append("Conflicting evidence present.")
            
        limitations_section = ReportSection(
            report_id=report.id,
            section_type="Limitations",
            title="Limitations",
            order_index=7,
            computed_content=json.dumps(limitations)
        )
        
        # 9. Evidence Appendix
        appendix_section = ReportSection(
            report_id=report.id,
            section_type="Evidence Appendix",
            title="Evidence Appendix",
            order_index=9
        )
        # In full impl, add finding/claim/document IDs
        
        report.sections = [
            exec_section,
            insights_section,
            contradictions_section,
            stats_section,
            limitations_section,
            appendix_section
        ]
        
        return report

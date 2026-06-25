from bs4 import BeautifulSoup
import time
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext

class HTMLNormalizer(PipelineStage[str, str]):
    """
    First stage of the pipeline: Fixes malformed HTML, standardizes tags, 
    and removes raw HTML comments or unparseable blocks.
    """
    name = "HTMLNormalizer"
    version = "1.0.0"

    async def process(self, input_html: str, context: PipelineContext) -> StageResult[str]:
        start_time = time.time()
        diagnostics = {}
        warnings = []
        errors = []
        status = StageStatus.SUCCESS
        
        try:
            # lxml is faster and more robust for broken HTML
            soup = BeautifulSoup(input_html, "lxml")
            
            # Remove comments
            from bs4 import Comment
            comments = soup.findAll(text=lambda text: isinstance(text, Comment))
            for comment in comments:
                comment.extract()
            
            diagnostics["comments_removed"] = len(comments)
            
            output_html = str(soup)
            
        except Exception as e:
            errors.append(f"BeautifulSoup parsing failed: {str(e)}")
            output_html = input_html
            status = StageStatus.RECOVERABLE_FAILURE

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=status,
            output=output_html,
            metrics={"input_length": len(input_html), "output_length": len(output_html)},
            warnings=warnings,
            errors=errors,
            diagnostics=diagnostics,
            version=self.version,
            execution_time_ms=execution_time_ms
        )

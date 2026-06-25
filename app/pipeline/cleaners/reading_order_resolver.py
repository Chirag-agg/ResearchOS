from bs4 import BeautifulSoup
import time
from typing import List
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext

class ReadingOrderResolver(PipelineStage[str, List[str]]):
    """
    Fourth stage of the pipeline: Recovers semantic reading order (e.g. left-to-right columns)
    rather than strictly relying on raw DOM order. Emits ordered HTML string blocks.
    """
    name = "ReadingOrderResolver"
    version = "1.0.0"

    async def process(self, input_html: str, context: PipelineContext) -> StageResult[List[str]]:
        start_time = time.time()
        
        soup = BeautifulSoup(input_html, "lxml")
        
        # In v1.0.0, we approximate reading order by isolating the <main> or <article> body,
        # flattening nested layouts, and linearizing blocks.
        
        main_content = soup.find("main") or soup.find("article") or soup.find("body") or soup
        
        # Block-level elements that constitute distinct reading flow items
        block_tags = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "figure", "ul", "ol", "pre", "math", "div"]
        
        blocks = []
        for elem in main_content.find_all(block_tags, recursive=True):
            # If a block contains other block tags directly, we might double-count.
            # A true reading order resolver requires layout geometry or deep CSS analysis.
            # For now, we extract leaf block elements or explicit containers.
            if elem.name == "div" and elem.find(block_tags):
                continue # Skip wrapper divs
                
            text_content = elem.get_text(strip=True)
            if text_content:
                blocks.append(str(elem))

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=blocks,
            metrics={"input_length": len(input_html), "blocks_recovered": len(blocks)},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

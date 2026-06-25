import re
import time
from typing import List
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext

class WhitespaceNormalizer(PipelineStage[List[str], List[str]]):
    """
    Fifth stage of the pipeline: Normalizes whitespace within textual blocks
    (e.g. collapsing multiple spaces, trimming newlines) while preserving
    structural whitespace in code blocks or equations.
    """
    name = "WhitespaceNormalizer"
    version = "1.0.0"

    async def process(self, input_blocks: List[str], context: PipelineContext) -> StageResult[List[str]]:
        start_time = time.time()
        
        normalized_blocks = []
        
        # Regex to collapse multiple spaces/newlines into a single space
        whitespace_pattern = re.compile(r'\s+')
        
        for block_html in input_blocks:
            # We avoid stripping whitespace inside <pre> or <code> blocks.
            # A true implementation would parse the DOM element. 
            # For this MVP string-based approach, we check tags loosely:
            if "<pre" in block_html or "<code" in block_html or "<math" in block_html:
                normalized_blocks.append(block_html.strip())
            else:
                # Collapse all internal whitespace
                collapsed = whitespace_pattern.sub(' ', block_html).strip()
                normalized_blocks.append(collapsed)

        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=normalized_blocks,
            metrics={"input_blocks": len(input_blocks), "output_blocks": len(normalized_blocks)},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

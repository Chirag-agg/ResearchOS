import unicodedata
import time
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext

class UnicodeNormalizer(PipelineStage[str, str]):
    """
    Second stage of the pipeline: Standardizes visual symbols, normalizes unicode 
    (NFKC), and unifies identical-looking characters (e.g. various hyphens, micro symbols).
    """
    name = "UnicodeNormalizer"
    version = "1.0.0"

    async def process(self, input_html: str, context: PipelineContext) -> StageResult[str]:
        start_time = time.time()
        
        # 1. NFKC Normalization (composed forms, standardizes width and compatibility characters)
        normalized = unicodedata.normalize('NFKC', input_html)
        
        # 2. Custom Replacements for known visual twins
        replacements = {
            "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",  # hyphens/dashes
            "μ": "μ", "µ": "μ",  # micro signs
            "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', # quotes
            "‘": "'", "’": "'", "‚": "'", "‹": "'", "›": "'",
            " ": " ", " ": " ", " ": " " # spaces
        }
        
        for k, v in replacements.items():
            normalized = normalized.replace(k, v)
            
        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=normalized,
            metrics={"input_length": len(input_html), "output_length": len(normalized)},
            version=self.version,
            execution_time_ms=execution_time_ms
        )

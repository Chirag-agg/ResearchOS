from bs4 import BeautifulSoup
import time
from app.pipeline.core import PipelineStage, StageResult, StageStatus, PipelineContext

class BoilerplateRemover(PipelineStage[str, str]):
    """
    Third stage of the pipeline: Aggressively removes noise like navigation,
    footers, sidebars, cookie banners, ads, but PRESERVES captions,
    equations, code blocks, tables, and references.
    """
    name = "BoilerplateRemover"
    version = "1.0.0"

    async def process(self, input_html: str, context: PipelineContext) -> StageResult[str]:
        start_time = time.time()
        warnings = []
        diagnostics = {"nodes_removed": 0}
        
        soup = BeautifulSoup(input_html, "lxml")
        
        # Tags to aggressively remove
        noise_tags = ["nav", "footer", "header", "aside", "script", "style", "noscript", "iframe"]
        
        # Classes/IDs commonly used for noise
        noise_classes = [
            "cookie", "banner", "ad", "advertisement", "social", "share", 
            "sidebar", "menu", "related", "recommended", "comments"
        ]
        
        # Protected tags (do NOT remove even if inside noise)
        protected_tags = ["table", "math", "code", "pre", "figure", "img"]
        
        removed_count = 0
        
        # 1. Remove obvious noise tags entirely
        for tag in soup.find_all(noise_tags):
            # Check if it contains protected tags. If so, unwrap or ignore.
            if any(tag.find_all(protected_tags)):
                warnings.append(f"Preserved {tag.name} because it contained protected elements.")
                continue
            tag.decompose()
            removed_count += 1
            
        # 2. Remove by class/id matching
        for elem in soup.find_all(class_=lambda x: x and any(c in str(x).lower() for c in noise_classes)):
            if any(elem.find_all(protected_tags)):
                continue
            elem.decompose()
            removed_count += 1
            
        for elem in soup.find_all(id=lambda x: x and any(c in str(x).lower() for c in noise_classes)):
            if any(elem.find_all(protected_tags)):
                continue
            elem.decompose()
            removed_count += 1
            
        diagnostics["nodes_removed"] = removed_count
        
        output_html = str(soup)
        execution_time_ms = (time.time() - start_time) * 1000

        return StageResult(
            status=StageStatus.SUCCESS,
            output=output_html,
            metrics={"input_length": len(input_html), "output_length": len(output_html)},
            warnings=warnings,
            diagnostics=diagnostics,
            version=self.version,
            execution_time_ms=execution_time_ms
        )

import hashlib
from typing import Dict

class PromptRegistry:
    """
    Centralized registry for all LLM prompts used in the system.
    This allows benchmarking to snapshot prompt versions by hashing the templates.
    """
    _templates: Dict[str, str] = {}
    
    @classmethod
    def register(cls, name: str, template: str) -> str:
        cls._templates[name] = template
        return template
        
    @classmethod
    def get_snapshot(cls) -> Dict[str, Dict[str, str]]:
        snapshot = {}
        for name, template in cls._templates.items():
            snapshot[name] = {
                "hash": hashlib.sha256(template.encode('utf-8')).hexdigest(),
                "text": template
            }
        return snapshot

# ==========================================
# PAGE UNDERSTANDING PROMPTS
# ==========================================

PAGE_UNDERSTANDING_TPL = PromptRegistry.register("page_understanding", """You are an expert research analyst...""") # Placeholder

# Let's populate these from the files directly in subsequent steps.

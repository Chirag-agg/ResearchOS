import json
import logging
import ast
from pathlib import Path
from typing import Dict, Any, List
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class BenchmarkCollector:
    """
    Collects artifacts and telemetry from a single benchmark run.
    """
    def __init__(self, run_id: str, base_dir: Path):
        self.run_id = run_id
        self.base_dir = base_dir
        self.run_dir = base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        self.artifacts = {
            "generated_queries": [],
            "fetched_pages": [],
            "raw_claims": [],
            "validated_claims": [],
            "knowledge_nodes": [],
            "telemetry": []
        }

    def collect(self, key: str, data: Any):
        """Append an item to a specific artifact collection."""
        if key in self.artifacts:
            if isinstance(data, list):
                self.artifacts[key].extend(data)
            else:
                self.artifacts[key].append(data)
        else:
            self.artifacts[key] = [data]

    def set_artifacts(self, key: str, data: List[Any]):
        """Set a collection completely."""
        self.artifacts[key] = data

    def extract_prompts_from_services(self, services_dir: Path):
        """Extract and hash string assignments to 'prompt' variables using AST."""
        prompts_snapshot = {}
        
        if not services_dir.exists():
            return
            
        for py_file in services_dir.glob("*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "prompt":
                                # Try to extract the string or f-string
                                prompt_text = None
                                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                    prompt_text = node.value.value
                                elif isinstance(node.value, ast.JoinedStr):
                                    # Very basic extraction for f-strings, just getting the raw source
                                    prompt_text = ast.unparse(node.value)
                                
                                if prompt_text:
                                    import hashlib
                                    prompt_hash = hashlib.sha256(prompt_text.encode('utf-8')).hexdigest()
                                    
                                    # Since there might be multiple prompts in a file, use line number
                                    key = f"{py_file.stem}_L{node.lineno}"
                                    prompts_snapshot[key] = {
                                        "hash": prompt_hash,
                                        "text": prompt_text
                                    }
            except Exception as e:
                logger.warning(f"Failed to parse prompts from {py_file}: {e}")
                
        self.artifacts["prompt_registry"] = prompts_snapshot

    def get_all(self) -> Dict[str, Any]:
        return self.artifacts

    def archive(self):
        """Save collected artifacts to disk."""
        archive_file = self.run_dir / "artifacts.json"
        
        # We need a safe serialization since these are often objects/models
        # For a production system we'd use model_dump(), here we'll assume they are dicts or can be cast
        
        def _safe_serialize(obj):
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            elif hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)
            
        try:
            with open(archive_file, "w", encoding="utf-8") as f:
                json.dump(self.artifacts, f, default=_safe_serialize, indent=2)
            logger.info(f"Archived benchmark artifacts to {archive_file}")
        except Exception as e:
            logger.error(f"Failed to archive benchmark artifacts: {e}")

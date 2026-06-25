from enum import Enum

class ValidationErrorCategory(str, Enum):
    PARSER = "PARSER"
    EXTRACTOR = "EXTRACTOR"
    SEMANTIC = "SEMANTIC"
    INFRASTRUCTURE = "INFRASTRUCTURE"

class ValidationErrorType(str, Enum):
    # Parser
    HTML = "HTML"
    STRUCTURE = "STRUCTURE"
    READING_ORDER = "READING_ORDER"
    
    # Extractor
    OFFSET = "OFFSET"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    
    # Semantic
    NEGATION = "NEGATION"
    ENTITY = "ENTITY"
    DUPLICATE = "DUPLICATE"
    CONTRADICTION = "CONTRADICTION"
    
    # Infrastructure
    TIMEOUT = "TIMEOUT"
    CACHE = "CACHE"
    SERIALIZATION = "SERIALIZATION"
    PROMPT = "PROMPT"

class ValidationError:
    def __init__(self, category: ValidationErrorCategory, type: ValidationErrorType, message: str, origin_stage: str = "Unknown", recoverable: bool = False):
        self.category = category
        self.type = type
        self.message = message
        self.origin_stage = origin_stage
        self.recoverable = recoverable

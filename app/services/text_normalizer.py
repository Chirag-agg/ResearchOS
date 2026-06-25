import unicodedata
import re

class TextNormalizer:
    """
    Centralized text normalization engine.
    Used by Extractor, Validator, Canonicalizer, and EvidenceLinker to ensure
    identical unicode, whitespace, and punctuation representations.
    """
    
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
            
        # 1. Unicode normalization (NFKC)
        # Translates compatibility characters to their canonical forms (e.g. μ -> μ, ﬁ -> fi)
        text = unicodedata.normalize('NFKC', text)
        
        # 2. Whitespace normalization
        # Replace newlines, tabs, and multiple spaces with a single space
        text = re.sub(r'\s+', ' ', text)
        
        # 3. Quote normalization
        # Standardize smart quotes and apostrophes
        text = re.sub(r'[\u2018\u2019\u201A\u201B\u00B4]', "'", text)
        text = re.sub(r'[\u201C\u201D\u201E\u201F\u00AB\u00BB]', '"', text)
        
        # 4. Hyphen/Dash normalization
        # Standardize en-dash, em-dash, minus, etc., to a simple hyphen
        text = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-', text)
        
        # Strip leading/trailing whitespace
        return text.strip()

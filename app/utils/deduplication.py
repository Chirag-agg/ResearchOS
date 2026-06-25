import urllib.parse
from typing import List, Set
from simhash import Simhash

# Common tracking parameters to strip
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "_ga", "mc_cid", "mc_eid"
}

def canonicalize_url(url: str) -> str:
    """
    Cleans and canonicalizes a URL to improve exact-match deduplication.
    - Lowercases scheme and netloc.
    - Removes default ports (80 for http, 443 for https).
    - Strips tracking parameters.
    - Removes trailing slashes from path.
    - Removes fragments unless it's a SPA-style route.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url
        
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Strip default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
        
    # Clean path (remove trailing slash unless it's the root)
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
        
    # Clean query params
    query = parsed.query
    if query:
        params = urllib.parse.parse_qsl(query, keep_blank_values=True)
        cleaned_params = [(k, v) for k, v in params if k.lower() not in TRACKING_PARAMS]
        query = urllib.parse.urlencode(cleaned_params)
        
    # Rebuild URL (drop fragment entirely for now, to aggregate sections of same page)
    canonical = urllib.parse.urlunparse((scheme, netloc, path, parsed.params, query, ""))
    
    # Simple http -> https normalizer (heuristic) if same domain
    if canonical.startswith("http://"):
        canonical = "https://" + canonical[7:]
        
    return canonical


def get_simhash(text: str) -> Simhash:
    """Returns the Simhash of a given text block."""
    # Convert to lowercase and split by whitespace
    tokens = text.lower().split()
    return Simhash(tokens)


def is_near_duplicate(hash1: Simhash, hash2: Simhash, tolerance: int = 3) -> bool:
    """
    Checks if two Simhashes are within a certain bit difference tolerance.
    For 64-bit simhash, a distance <= 3 usually means very similar text.
    """
    return hash1.distance(hash2) <= tolerance

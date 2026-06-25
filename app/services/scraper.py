import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from playwright.async_api import async_playwright, Browser, BrowserContext

logger = logging.getLogger(__name__)


# --- Tracking parameters stripped when computing canonical URLs ---
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "dclid", "msclkid",
}


@dataclass
class PageContent:
    """
    Intermediate data object returned by ScraperService before persistence.
    Contains everything needed to construct a FetchedPage row.
    """
    url: str
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    content: str = ""
    content_hash: str = ""
    content_length: int = 0
    raw_html_path: Optional[str] = None
    extraction_quality_score: float = 0.0
    fetch_status: str = "pending"
    error_message: Optional[str] = None
    metadata_: Optional[str] = None


class ScraperError(Exception):
    """
    Base exception raised by ScraperService for unrecoverable failures.
    """
    pass


class BrowserManager:
    """
    Manages a single shared Chromium browser instance with a reusable context.
    Runs Playwright in a dedicated background thread with its own event loop
    to prevent Windows SelectorEventLoop subprocess issues under Uvicorn.
    """

    def __init__(self, timeout_ms: int = 30000):
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._lock = asyncio.Lock()

    def _thread_worker(self):
        """Worker function for the Playwright dedicated thread."""
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
            
        asyncio.set_event_loop(loop)
        self._loop = loop
        
        loop.run_until_complete(self._start_playwright())
        self._ready_event.set()
        
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self._stop_playwright())
            loop.close()

    async def _start_playwright(self):
        logger.info("Launching shared Chromium browser instance in background thread...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        logger.info("Chromium browser ready.")

    async def _stop_playwright(self):
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Chromium browser shut down.")

    async def start(self) -> None:
        """Start the Playwright background thread if not running."""
        async with self._lock:
            if self._thread is not None:
                return

            self._thread = threading.Thread(target=self._thread_worker, daemon=True)
            self._thread.start()
            await asyncio.to_thread(self._ready_event.wait)

    async def stop(self) -> None:
        """Gracefully shut down the browser thread."""
        async with self._lock:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
                await asyncio.to_thread(self._thread.join)
            self._thread = None
            self._loop = None

    async def _do_fetch(self, url: str) -> tuple[Optional[str], str]:
        """Internal coroutine that runs on the background loop."""
        page = await self._context.new_page()
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms
            )
            title = await page.title()
            raw_html = await page.content()
            return title, raw_html
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def fetch(self, url: str) -> tuple[Optional[str], str]:
        """Fetch a page by dispatching to the background thread."""
        if not self._loop:
            await self.start()
        future = asyncio.run_coroutine_threadsafe(self._do_fetch(url), self._loop)
        return await asyncio.wrap_future(future)

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms


class ScraperService:
    """
    Service responsible for fetching web pages via Playwright and extracting
    clean text content via Trafilatura.

    Uses a BrowserManager for shared Chromium instance (single browser,
    multiple tabs) and stores raw HTML to disk for future re-extraction.
    """

    def __init__(self, timeout_ms: int = 30000, html_storage_dir: str = "storage/html"):
        self._browser_manager = BrowserManager(timeout_ms=timeout_ms)
        self._html_storage_dir = html_storage_dir

    async def start(self) -> None:
        """Initialize the browser. Call once before fetching."""
        await self._browser_manager.start()

    async def stop(self) -> None:
        """Shut down the browser. Call during application shutdown."""
        await self._browser_manager.stop()

    async def fetch_and_extract(self, url: str) -> PageContent:
        """
        Fetch a single URL and extract clean text content.

        Pipeline:
        1. Open page tab in shared Chromium
        2. Navigate to URL (wait for DOM content loaded)
        3. Extract raw HTML
        4. Store raw HTML to disk
        5. Extract clean text via Trafilatura
        6. Compute content_hash (SHA256), content_length, canonical_url
        7. Calculate extraction_quality_score

        This method never raises — failures are captured in PageContent.fetch_status
        so one bad URL doesn't tank the entire batch.
        """
        try:
            logger.info(f"Fetching URL: {url}")
            
            # Fetch using the background Playwright thread
            title, raw_html = await self._browser_manager.fetch(url)

            # Store raw HTML to disk
            raw_html_path = self._store_raw_html(url, raw_html)

            # Extract clean text with Trafilatura
            content, metadata = self._extract_content(raw_html, url)

            # Compute derived fields
            content_hash = self._compute_hash(content)
            content_length = len(content)
            canonical_url = self._compute_canonical_url(url)
            quality_score = self._compute_quality_score(content)

            return PageContent(
                url=url,
                canonical_url=canonical_url,
                title=title or None,
                content=content,
                content_hash=content_hash,
                content_length=content_length,
                raw_html_path=raw_html_path,
                extraction_quality_score=quality_score,
                fetch_status="success",
                metadata_=json.dumps(metadata) if metadata else None,
            )

        except Exception as e:
            error_type = type(e).__name__

            # Distinguish timeout from generic failures
            if "timeout" in error_type.lower() or "timeout" in str(e).lower():
                fetch_status = "timeout"
                logger.warning(f"Timeout fetching {url}: {e}")
            else:
                fetch_status = "failed"
                logger.error(f"Failed to fetch {url}: {e}")

            return PageContent(
                url=url,
                canonical_url=self._compute_canonical_url(url),
                fetch_status=fetch_status,
                error_message=f"{error_type}: {str(e)[:500]}",
                content_hash=self._compute_hash(""),
            )

    def _store_raw_html(self, url: str, html: str) -> Optional[str]:
        """
        Persist raw HTML to disk under storage/html/<hash>.html.
        Returns the relative file path, or None on failure.
        """
        try:
            os.makedirs(self._html_storage_dir, exist_ok=True)

            # Use URL hash for the filename to avoid filesystem-unsafe characters
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
            filename = f"{url_hash}.html"
            filepath = os.path.join(self._html_storage_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)

            logger.debug(f"Stored raw HTML: {filepath}")
            return filepath

        except Exception as e:
            logger.warning(f"Failed to store raw HTML for {url}: {e}")
            return None

    @staticmethod
    def _extract_content(html: str, url: str) -> tuple[str, dict]:
        """
        Extract clean text content from raw HTML using Trafilatura.
        Returns (extracted_text, metadata_dict).
        """
        # Import here to avoid import-time side effects and allow mocking
        import trafilatura

        try:
            result = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                include_links=False,
                favor_precision=True,
                deduplicate=True,
            )

            content = result or ""

            # Extract metadata separately
            metadata = {}
            try:
                meta = trafilatura.extract_metadata(html, default_url=url)
                if meta:
                    metadata = {
                        "author": meta.author,
                        "date": meta.date,
                        "sitename": meta.sitename,
                        "description": meta.description,
                        "categories": meta.categories if hasattr(meta, "categories") else [],
                    }
            except Exception:
                pass  # Metadata extraction is best-effort

            return content, metadata

        except Exception as e:
            logger.warning(f"Trafilatura extraction failed for {url}: {e}")
            return "", {}

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute SHA256 hex digest of the content string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_canonical_url(url: str) -> str:
        """
        Strip tracking parameters (utm_*, ref, fbclid, etc.) to produce
        a canonical URL for deduplication.
        """
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query, keep_blank_values=False)

            # Remove known tracking parameters
            cleaned_params = {
                k: v for k, v in query_params.items()
                if k.lower() not in _TRACKING_PARAMS
            }

            # Reconstruct URL with cleaned query string
            clean_query = urlencode(cleaned_params, doseq=True)
            canonical = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path.rstrip("/"),  # Normalize trailing slash
                parsed.params,
                clean_query,
                "",  # Drop fragment
            ))

            return canonical

        except Exception:
            return url

    @staticmethod
    def _compute_quality_score(content: str) -> float:
        """
        Simple heuristic quality score based on word count.
        Enables future filtering of thin/empty pages without re-parsing.
        """
        if not content:
            return 0.0

        word_count = len(content.split())

        if word_count < 100:
            return 0.1
        elif word_count < 500:
            return 0.5
        else:
            return 1.0

import json
import logging
import time
import asyncio
import threading
import re
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

import psutil

from app.models.base import get_utc_now
from app.models.llm_metrics import LLMCallMetrics
from app.models.telemetry import (
    TelemetryEvent,
    TelemetryEventType,
    TelemetryStage,
    TelemetryEventRead,
    ResearchMetrics,
    ResearchLiveStatus,
    QueueMetrics,
    DebugReport,
    DebugReportSlowest,
    LiveResearchStatus,
)
from app.repositories.telemetry import TelemetryRepository

logger = logging.getLogger(__name__)


class TelemetryBroadcaster:
    """
    Thread-safe broadcaster that routes telemetry events to active client streams.
    Allows multiple subscribers per session, and automatically manages cleanup.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._subscribers: Dict[UUID, Set[asyncio.Queue]] = {}
        self._subscription_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "TelemetryBroadcaster":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = TelemetryBroadcaster()
        return cls._instance

    async def subscribe(self, session_id: UUID) -> asyncio.Queue:
        async with self._subscription_lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = set()
            q = asyncio.Queue()
            self._subscribers[session_id].add(q)
            logger.debug(f"Subscriber added for session {session_id}. Active: {len(self._subscribers[session_id])}")
            return q

    async def unsubscribe(self, session_id: UUID, q: asyncio.Queue):
        async with self._subscription_lock:
            if session_id in self._subscribers:
                self._subscribers[session_id].discard(q)
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]
                logger.debug(f"Subscriber removed for session {session_id}.")

    async def broadcast(self, session_id: UUID, event: TelemetryEvent):
        async with self._subscription_lock:
            queues = list(self._subscribers.get(session_id, []))
        for q in queues:
            await q.put(event)


class TelemetryService:
    """
    Central telemetry service for recording, querying, and aggregating
    research pipeline instrumentation data.

    Every track_* method persists a TelemetryEvent row immediately.
    System metrics (CPU, RAM) are captured on every event via psutil.
    """

    def __init__(self, session_maker, broadcaster=None):
        self._session_maker = session_maker
        self._process = psutil.Process()
        self.broadcaster = broadcaster or TelemetryBroadcaster.get_instance()

    def _capture_system_metrics(self) -> dict:
        """Snapshot CPU % and process memory in MB."""
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem_info = self._process.memory_info()
            memory_mb = round(mem_info.rss / (1024 * 1024), 2)
            return {"cpu_percent": cpu, "memory_mb": memory_mb}
        except Exception:
            return {"cpu_percent": None, "memory_mb": None}

    async def _persist(self, event: TelemetryEvent) -> TelemetryEvent:
        """Write a single telemetry event to the database."""
        async with self._session_maker() as session:
            repo = TelemetryRepository(session)
            persisted = await repo.create(event)
        if self.broadcaster:
            await self.broadcaster.broadcast(event.session_id, persisted)
        return persisted

    async def track_start(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        message: Optional[str] = None,
        research_round: Optional[int] = None,
        url: Optional[str] = None,
        page_id: Optional[str] = None,
        query_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record the start of a pipeline stage. Returns the event for pairing with track_end."""
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            stage=stage,
            event_type=TelemetryEventType.STARTED,
            message=message,
            url=url,
            page_id=page_id,
            query_id=query_id,
            claim_id=claim_id,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_end(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        started_event: TelemetryEvent,
        message: Optional[str] = None,
        research_round: Optional[int] = None,
        url: Optional[str] = None,
        page_id: Optional[str] = None,
        query_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record the end of a pipeline stage. Computes duration_ms from the started_event."""
        now = get_utc_now()
        duration_ms = (now - started_event.timestamp).total_seconds() * 1000
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            timestamp=now,
            stage=stage,
            event_type=TelemetryEventType.COMPLETED,
            message=message,
            duration_ms=round(duration_ms, 2),
            url=url,
            page_id=page_id,
            query_id=query_id,
            claim_id=claim_id,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_failed(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        started_event: Optional[TelemetryEvent] = None,
        message: Optional[str] = None,
        research_round: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record a failed pipeline stage."""
        now = get_utc_now()
        duration_ms = None
        if started_event:
            duration_ms = round((now - started_event.timestamp).total_seconds() * 1000, 2)
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            timestamp=now,
            stage=stage,
            event_type=TelemetryEventType.FAILED,
            message=message,
            duration_ms=duration_ms,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_progress(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        message: str,
        research_round: Optional[int] = None,
        url: Optional[str] = None,
        page_id: Optional[str] = None,
        query_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record an intermediate progress update."""
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            stage=stage,
            event_type=TelemetryEventType.PROGRESS,
            message=message,
            url=url,
            page_id=page_id,
            query_id=query_id,
            claim_id=claim_id,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_metric(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        message: str,
        research_round: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record an arbitrary measured value."""
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            stage=stage,
            event_type=TelemetryEventType.METRIC,
            message=message,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_llm_call(
        self,
        session_id: UUID,
        stage: TelemetryStage,
        llm_metrics: LLMCallMetrics,
        research_round: Optional[int] = None,
        page_id: Optional[str] = None,
        claim_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """
        Record an LLM call with native Ollama metrics.
        Captures: model, tokens, durations, load time, generation time.
        """
        sys_metrics = self._capture_system_metrics()
        meta = {
            "model_name": llm_metrics.model_name,
            "prompt_tokens": llm_metrics.prompt_tokens,
            "completion_tokens": llm_metrics.completion_tokens,
            "total_tokens": llm_metrics.total_tokens,
            "total_duration_ms": llm_metrics.total_duration_ms,
            "load_duration_ms": llm_metrics.load_duration_ms,
            "prompt_eval_duration_ms": llm_metrics.prompt_eval_duration_ms,
            "eval_duration_ms": llm_metrics.eval_duration_ms,
            "prompt_chars": llm_metrics.prompt_chars,
            "response_chars": llm_metrics.response_chars,
            "retries": llm_metrics.retries,
        }
        event = TelemetryEvent(
            session_id=session_id,
            stage=stage,
            event_type=TelemetryEventType.LLM_CALL_COMPLETED,
            message=f"LLM call: {llm_metrics.model_name} ({llm_metrics.total_tokens} tokens, {llm_metrics.total_duration_ms}ms)",
            duration_ms=llm_metrics.total_duration_ms,
            tokens_input=llm_metrics.prompt_tokens,
            tokens_output=llm_metrics.completion_tokens,
            llm_call_id=str(llm_metrics.llm_call_id),
            page_id=page_id,
            claim_id=claim_id,
            research_round=research_round,
            metadata_json=json.dumps(meta),
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_url_event(
        self,
        session_id: UUID,
        event_type: TelemetryEventType,
        url: str,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        research_round: Optional[int] = None,
        page_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record a URL lifecycle event (queued, fetch started/completed, extraction started/completed)."""
        sys_metrics = self._capture_system_metrics()
        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.FETCH,
            event_type=event_type,
            message=message,
            duration_ms=duration_ms,
            url=url,
            page_id=page_id,
            research_round=research_round,
            metadata_json=json.dumps(metadata) if metadata else None,
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_chunk_event(
        self,
        session_id: UUID,
        event_type: TelemetryEventType,
        page_id: str,
        url: str,
        chunk_index: int,
        chunk_size: int,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        research_round: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> TelemetryEvent:
        """Record a chunk processing lifecycle event."""
        sys_metrics = self._capture_system_metrics()
        meta = metadata or {}
        meta.update({
            "chunk_index": chunk_index,
            "chunk_size": chunk_size,
        })
        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.CLAIM_EXTRACTION,
            event_type=event_type,
            message=message,
            duration_ms=duration_ms,
            url=url,
            page_id=page_id,
            research_round=research_round,
            metadata_json=json.dumps(meta),
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_page_processing(
        self,
        session_id: UUID,
        url: str,
        fetch_duration_ms: float,
        html_size_bytes: int,
        extracted_text_size: int,
        extraction_duration_ms: float,
        research_round: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """Record complete page processing metrics."""
        sys_metrics = self._capture_system_metrics()
        meta = {
            "fetch_duration_ms": fetch_duration_ms,
            "html_size_bytes": html_size_bytes,
            "extracted_text_size": extracted_text_size,
            "extraction_duration_ms": extraction_duration_ms,
        }
        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.FETCH,
            event_type=TelemetryEventType.METRIC,
            message=f"Page processed: {url} ({extracted_text_size} chars extracted)",
            url=url,
            page_id=page_id,
            research_round=research_round,
            metadata_json=json.dumps(meta),
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_query_processing(
        self,
        session_id: UUID,
        query: str,
        search_engine: str,
        results_count: int,
        duration_ms: float,
        research_round: Optional[int] = None,
        query_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """Record search query execution metrics."""
        sys_metrics = self._capture_system_metrics()
        meta = {
            "query": query,
            "search_engine": search_engine,
            "results_count": results_count,
        }
        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.SEARCH,
            event_type=TelemetryEventType.METRIC,
            message=f"Search: '{query}' → {results_count} results ({duration_ms}ms)",
            duration_ms=duration_ms,
            query_id=query_id,
            research_round=research_round,
            metadata_json=json.dumps(meta),
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    async def track_queue_metrics(
        self,
        session_id: UUID,
        queued: int,
        active: int,
        completed: int,
        failed: int,
        research_round: Optional[int] = None,
    ) -> TelemetryEvent:
        """Record current page queue state."""
        sys_metrics = self._capture_system_metrics()
        meta = {
            "queued_pages": queued,
            "active_pages": active,
            "completed_pages": completed,
            "failed_pages": failed,
        }
        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.FETCH,
            event_type=TelemetryEventType.METRIC,
            message=f"Queue: {queued} queued, {active} active, {completed} done, {failed} failed",
            research_round=research_round,
            metadata_json=json.dumps(meta),
            cpu_percent=sys_metrics["cpu_percent"],
            memory_mb=sys_metrics["memory_mb"],
        )
        return await self._persist(event)

    # --- Aggregation Queries ---

    async def get_events(self, session_id: UUID) -> List[TelemetryEvent]:
        """Retrieve all telemetry events for a session in chronological order."""
        async with self._session_maker() as session:
            repo = TelemetryRepository(session)
            return await repo.get_by_session(session_id)

    async def compute_metrics(self, session_id: UUID, question: str = "") -> ResearchMetrics:
        """Aggregate all telemetry events into per-stage duration totals and counts."""
        events = await self.get_events(session_id)

        metrics = ResearchMetrics(session_id=session_id, question=question)

        if not events:
            return metrics

        # Find session boundaries
        metrics.started_at = events[0].timestamp
        metrics.finished_at = events[-1].timestamp
        if metrics.started_at and metrics.finished_at:
            metrics.total_duration_ms = round(
                (metrics.finished_at - metrics.started_at).total_seconds() * 1000, 2
            )

        # Stage duration mapping
        stage_duration_map = {
            TelemetryStage.QUERY_GENERATION: "query_generation_duration_ms",
            TelemetryStage.SEARCH: "search_duration_ms",
            TelemetryStage.FETCH: "fetch_duration_ms",
            TelemetryStage.PAGE_ANALYSIS: "page_analysis_duration_ms",
            TelemetryStage.CLAIM_EXTRACTION: "claim_extraction_duration_ms",
            TelemetryStage.VALIDATION: "validation_duration_ms",
            TelemetryStage.KNOWLEDGE_BUILDING: "knowledge_duration_ms",
            TelemetryStage.REPORT_GENERATION: "report_duration_ms",
        }

        stage_totals: Dict[str, float] = {}

        for event in events:
            # Sum completed event durations per stage
            if event.event_type == TelemetryEventType.COMPLETED and event.duration_ms:
                attr_name = stage_duration_map.get(event.stage)
                if attr_name:
                    current = getattr(metrics, attr_name, 0.0)
                    setattr(metrics, attr_name, round(current + event.duration_ms, 2))
                    stage_totals[event.stage.value] = stage_totals.get(event.stage.value, 0.0) + event.duration_ms

            # Count LLM calls and tokens
            if event.event_type == TelemetryEventType.LLM_CALL_COMPLETED:
                metrics.llm_calls += 1
                if event.tokens_input:
                    metrics.total_input_tokens += event.tokens_input
                if event.tokens_output:
                    metrics.total_output_tokens += event.tokens_output

            # Count URL events for page metrics
            if event.event_type == TelemetryEventType.URL_QUEUED:
                metrics.total_pages += 1
            if event.event_type == TelemetryEventType.URL_FETCH_COMPLETED:
                if event.metadata_json:
                    try:
                        meta = json.loads(event.metadata_json)
                        if meta.get("fetch_status") == "success":
                            metrics.processed_pages += 1
                        elif meta.get("fetch_status") in ("failed", "timeout"):
                            metrics.failed_pages += 1
                    except Exception:
                        metrics.processed_pages += 1
                else:
                    metrics.processed_pages += 1

            # Count chunk completion events for claim tracking
            if event.event_type == TelemetryEventType.CHUNK_PROCESSING_COMPLETED:
                if event.metadata_json:
                    try:
                        meta = json.loads(event.metadata_json)
                        metrics.total_claims += meta.get("claims_extracted", 0)
                    except Exception:
                        pass

        # Find most expensive stage
        if stage_totals:
            metrics.most_expensive_stage = max(stage_totals, key=stage_totals.get)

        # Compute efficiency metrics
        total_tokens = metrics.total_input_tokens + metrics.total_output_tokens
        if metrics.total_claims > 0 and total_tokens > 0:
            metrics.tokens_per_claim = round(total_tokens / metrics.total_claims, 1)
        if metrics.validated_claims > 0 and total_tokens > 0:
            metrics.tokens_per_validated_claim = round(total_tokens / metrics.validated_claims, 1)

        return metrics

    async def get_live_status(self, session_id: UUID) -> ResearchLiveStatus:
        """Determine current status from the most recent telemetry events."""
        events = await self.get_events(session_id)

        status = ResearchLiveStatus(session_id=session_id)

        if not events:
            return status

        # Elapsed time
        first_event = events[0]
        last_event = events[-1]
        status.elapsed_ms = round(
            (last_event.timestamp - first_event.timestamp).total_seconds() * 1000, 2
        )

        # Current stage = the stage of the most recent event
        status.current_stage = last_event.stage.value

        # Current round
        for event in reversed(events):
            if event.research_round is not None:
                status.current_round = event.research_round
                break

        # Current URL = most recent URL in events
        for event in reversed(events):
            if event.url:
                status.current_url = event.url
                break

        # Page progress
        queued = 0
        active_urls = set()
        completed = 0
        failed = 0

        for event in events:
            if event.event_type == TelemetryEventType.URL_QUEUED and event.url:
                queued += 1
            if event.event_type == TelemetryEventType.URL_FETCH_STARTED and event.url:
                active_urls.add(event.url)
            if event.event_type == TelemetryEventType.URL_FETCH_COMPLETED and event.url:
                active_urls.discard(event.url)
                completed += 1
            if event.event_type == TelemetryEventType.FAILED and event.url:
                active_urls.discard(event.url)
                failed += 1

        status.pages_processed = completed
        status.pages_remaining = max(0, queued - completed - failed)
        status.queue_metrics = QueueMetrics(
            queued=queued,
            active=len(active_urls),
            completed=completed,
            failed=failed,
        )

        # Progress percent
        total = queued if queued > 0 else 1
        status.progress_percent = round((completed / total) * 100, 1) if queued > 0 else 0.0

        # System metrics from latest event
        status.cpu_percent = last_event.cpu_percent
        status.memory_mb = last_event.memory_mb

        return status

    async def compute_debug_report(self, session_id: UUID, question: str = "") -> DebugReport:
        """
        Build a comprehensive debug report: durations, token usage,
        slowest pages/queries/LLM calls, and efficiency metrics.
        """
        events = await self.get_events(session_id)
        metrics = await self.compute_metrics(session_id, question)

        report = DebugReport(session_id=session_id)

        # Durations
        report.durations = {
            "total_ms": metrics.total_duration_ms,
            "query_generation_ms": metrics.query_generation_duration_ms,
            "search_ms": metrics.search_duration_ms,
            "fetch_ms": metrics.fetch_duration_ms,
            "page_analysis_ms": metrics.page_analysis_duration_ms,
            "claim_extraction_ms": metrics.claim_extraction_duration_ms,
            "validation_ms": metrics.validation_duration_ms,
            "knowledge_ms": metrics.knowledge_duration_ms,
            "report_ms": metrics.report_duration_ms,
        }

        # Token usage
        report.token_usage = {
            "total_input_tokens": metrics.total_input_tokens,
            "total_output_tokens": metrics.total_output_tokens,
            "total_tokens": metrics.total_input_tokens + metrics.total_output_tokens,
            "llm_calls": metrics.llm_calls,
        }

        report.most_expensive_stage = metrics.most_expensive_stage
        report.tokens_per_claim = metrics.tokens_per_claim
        report.tokens_per_validated_claim = metrics.tokens_per_validated_claim

        # Slowest pages (by fetch duration)
        page_events = [
            e for e in events
            if e.event_type == TelemetryEventType.URL_FETCH_COMPLETED and e.duration_ms
        ]
        page_events.sort(key=lambda e: e.duration_ms or 0, reverse=True)
        report.slowest_pages = [
            DebugReportSlowest(
                identifier=e.url or "unknown",
                duration_ms=e.duration_ms or 0,
                stage="fetch",
            )
            for e in page_events[:10]
        ]

        # Slowest queries (by search duration)
        query_events = [
            e for e in events
            if e.stage == TelemetryStage.SEARCH
            and e.event_type == TelemetryEventType.METRIC
            and e.duration_ms
        ]
        query_events.sort(key=lambda e: e.duration_ms or 0, reverse=True)
        report.slowest_queries = [
            DebugReportSlowest(
                identifier=json.loads(e.metadata_json).get("query", "unknown") if e.metadata_json else "unknown",
                duration_ms=e.duration_ms or 0,
                stage="search",
            )
            for e in query_events[:10]
        ]

        # Slowest LLM calls
        llm_events = [
            e for e in events
            if e.event_type == TelemetryEventType.LLM_CALL_COMPLETED and e.duration_ms
        ]
        llm_events.sort(key=lambda e: e.duration_ms or 0, reverse=True)
        report.slowest_llm_calls = [
            DebugReportSlowest(
                identifier=e.llm_call_id or "unknown",
                duration_ms=e.duration_ms or 0,
                stage=e.stage.value,
                metadata=json.loads(e.metadata_json) if e.metadata_json else None,
            )
            for e in llm_events[:10]
        ]

        return report

    async def get_live_research_status(self, session_id: UUID) -> LiveResearchStatus:
        """Calculate and return a detailed real-time snapshot of the running research session."""
        events = await self.get_events(session_id)
        
        status = LiveResearchStatus(
            session_id=session_id,
            current_stage="session",
            progress_percent=0.0,
            pages_completed=0,
            pages_total=0,
            claims_extracted=0,
            validated_claims=0,
            current_url=None,
            current_chunk=None,
            total_chunks=None,
            cpu_percent=0.0,
            memory_mb=0.0,
            llm_calls=0,
            input_tokens=0,
            output_tokens=0,
        )

        if not events:
            return status

        # Latest event for stage, CPU, memory
        latest_event = events[-1]
        status.current_stage = latest_event.stage.value if hasattr(latest_event.stage, "value") else str(latest_event.stage)
        status.cpu_percent = latest_event.cpu_percent or 0.0
        status.memory_mb = latest_event.memory_mb or 0.0

        # Current URL is the most recent URL seen in any event
        for event in reversed(events):
            if event.url:
                status.current_url = event.url
                break

        # Process events to count pages, claims, validations, llm calls, tokens
        for event in events:
            # Page totals and completions
            if event.event_type == TelemetryEventType.URL_QUEUED:
                status.pages_total += 1
            elif event.event_type == TelemetryEventType.URL_FETCH_COMPLETED:
                if event.metadata_json:
                    try:
                        meta = json.loads(event.metadata_json)
                        if meta.get("fetch_status") == "success":
                            status.pages_completed += 1
                    except Exception:
                        status.pages_completed += 1
                else:
                    status.pages_completed += 1

            # Claim extraction count
            elif event.event_type == TelemetryEventType.CHUNK_PROCESSING_COMPLETED:
                if event.metadata_json:
                    try:
                        meta = json.loads(event.metadata_json)
                        status.claims_extracted += meta.get("claims_extracted", 0)
                    except Exception:
                        pass

            # Validated claims count (count progress events in VALIDATION stage)
            elif event.stage == TelemetryStage.VALIDATION and event.event_type == TelemetryEventType.PROGRESS:
                status.validated_claims += 1

            # LLM metrics
            elif event.event_type == TelemetryEventType.LLM_CALL_COMPLETED:
                status.llm_calls += 1
                if event.tokens_input:
                    status.input_tokens += event.tokens_input
                if event.tokens_output:
                    status.output_tokens += event.tokens_output

        # Chunk progress (regex parse from latest chunk processing message)
        chunk_events = [e for e in events if e.event_type in (TelemetryEventType.CHUNK_PROCESSING_STARTED, TelemetryEventType.CHUNK_PROCESSING_COMPLETED)]
        if chunk_events:
            latest_chunk = chunk_events[-1]
            if latest_chunk.message:
                match = re.search(r"Chunk (\d+)/(\d+)", latest_chunk.message)
                if match:
                    status.current_chunk = int(match.group(1))
                    status.total_chunks = int(match.group(2))

        # Extract page progress for CLAIM_EXTRACTION stage from progress messages
        extraction_events = [e for e in events if e.stage == TelemetryStage.CLAIM_EXTRACTION and e.event_type == TelemetryEventType.PROGRESS]
        current_extraction_page = 0
        total_extraction_pages = 0
        if extraction_events:
            latest_ext = extraction_events[-1]
            if latest_ext.message:
                match = re.search(r"Page (\d+)/(\d+)", latest_ext.message)
                if match:
                    current_extraction_page = int(match.group(1))
                    total_extraction_pages = int(match.group(2))

        # Progress percentage based on stage
        stage = latest_event.stage
        if stage == TelemetryStage.QUERY_GENERATION:
            status.progress_percent = 10.0
        elif stage == TelemetryStage.SEARCH:
            status.progress_percent = 20.0
        elif stage == TelemetryStage.FETCH:
            pct = 20.0
            if status.pages_total > 0:
                pct += (status.pages_completed / status.pages_total) * 30.0
            status.progress_percent = round(pct, 1)
        elif stage == TelemetryStage.CLAIM_EXTRACTION:
            pct = 50.0
            if total_extraction_pages > 0:
                pct += (current_extraction_page / total_extraction_pages) * 30.0
            status.progress_percent = round(pct, 1)
        elif stage == TelemetryStage.VALIDATION:
            pct = 80.0
            if status.claims_extracted > 0:
                pct += (status.validated_claims / status.claims_extracted) * 20.0
            status.progress_percent = round(pct, 1)
        elif stage == TelemetryStage.SESSION:
            if latest_event.event_type == TelemetryEventType.COMPLETED:
                status.progress_percent = 100.0
            elif latest_event.event_type == TelemetryEventType.FAILED:
                status.progress_percent = 100.0
            else:
                status.progress_percent = 0.0
        else:
            # Fallback or other stages (like knowledge building, gap discovery, planning, report gen)
            if stage == TelemetryStage.KNOWLEDGE_BUILDING:
                status.progress_percent = 90.0
            elif stage == TelemetryStage.GAP_DISCOVERY:
                status.progress_percent = 93.0
            elif stage == TelemetryStage.PLANNING:
                status.progress_percent = 95.0
            elif stage == TelemetryStage.REPORT_GENERATION:
                status.progress_percent = 98.0
            else:
                status.progress_percent = 100.0

        return status

    def format_stream_payload(self, event: TelemetryEvent, progress_percent: float) -> dict:
        """Format a TelemetryEvent to the specified stream event dictionary payload."""
        metadata = {}
        if event.metadata_json:
            try:
                metadata = json.loads(event.metadata_json)
            except Exception:
                pass
        return {
            "timestamp": event.timestamp.isoformat(),
            "stage": event.stage.value if hasattr(event.stage, "value") else str(event.stage),
            "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            "message": event.message or "",
            "progress_percent": progress_percent,
            "cpu_percent": event.cpu_percent or 0.0,
            "memory_mb": event.memory_mb or 0.0,
            "metadata": metadata,
        }


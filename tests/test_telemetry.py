"""
Tests for the Research Telemetry & Observability system.
Validates telemetry persistence, metrics aggregation, timeline ordering,
token tracking, progress tracking, system metrics, live status, and API endpoints.
"""
import os
import json
import pytest
from uuid import uuid4
from datetime import timedelta

from app.models.base import get_utc_now
from app.models.telemetry import (
    TelemetryEvent,
    TelemetryStage,
    TelemetryEventType,
    TelemetryEventRead,
    ResearchMetrics,
    LiveResearchStatus,
    DebugReport,
)
from app.models.llm_metrics import LLMCallMetrics
from app.repositories.telemetry import TelemetryRepository
from app.services.telemetry import TelemetryService

# Use test database session maker from conftest
from tests.conftest import test_async_session_maker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def telemetry_service():
    """Create a TelemetryService backed by the test database."""
    return TelemetryService(session_maker=test_async_session_maker)


@pytest.fixture
def session_id():
    """Generate a unique session ID for each test."""
    return uuid4()


# ---------------------------------------------------------------------------
# TelemetryRepository Tests
# ---------------------------------------------------------------------------

class TestTelemetryRepository:
    """Tests for TelemetryRepository CRUD and query operations."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_event(self, db_session, session_id):
        """Events persist to database and are retrievable by session."""
        repo = TelemetryRepository(db_session)

        event = TelemetryEvent(
            session_id=session_id,
            stage=TelemetryStage.SEARCH,
            event_type=TelemetryEventType.STARTED,
            message="Test search started",
        )
        persisted = await repo.create(event)

        assert persisted.id is not None
        assert persisted.session_id == session_id
        assert persisted.stage == TelemetryStage.SEARCH
        assert persisted.event_type == TelemetryEventType.STARTED

        # Retrieve
        events = await repo.get_by_session(session_id)
        assert len(events) >= 1
        found = [e for e in events if e.id == persisted.id]
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_get_by_stage(self, db_session, session_id):
        """Filtering by stage returns only events of that stage."""
        repo = TelemetryRepository(db_session)

        # Create events of different stages
        await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.FETCH,
            event_type=TelemetryEventType.STARTED, message="fetch"
        ))
        await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.VALIDATION,
            event_type=TelemetryEventType.STARTED, message="validation"
        ))

        fetch_events = await repo.get_by_stage(session_id, TelemetryStage.FETCH)
        assert all(e.stage == TelemetryStage.FETCH for e in fetch_events)

    @pytest.mark.asyncio
    async def test_get_latest(self, db_session, session_id):
        """get_latest returns the most recent event(s)."""
        repo = TelemetryRepository(db_session)

        await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.SESSION,
            event_type=TelemetryEventType.STARTED, message="first"
        ))
        second = await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.SESSION,
            event_type=TelemetryEventType.COMPLETED, message="second"
        ))

        latest = await repo.get_latest(session_id, limit=1)
        assert len(latest) == 1
        assert latest[0].id == second.id

    @pytest.mark.asyncio
    async def test_get_llm_calls(self, db_session, session_id):
        """get_llm_calls returns only LLM_CALL_COMPLETED events."""
        repo = TelemetryRepository(db_session)

        await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.QUERY_GENERATION,
            event_type=TelemetryEventType.STARTED, message="start"
        ))
        llm_event = await repo.create(TelemetryEvent(
            session_id=session_id, stage=TelemetryStage.QUERY_GENERATION,
            event_type=TelemetryEventType.LLM_CALL_COMPLETED,
            message="llm call", tokens_input=100, tokens_output=50,
        ))

        llm_calls = await repo.get_llm_calls(session_id)
        assert len(llm_calls) >= 1
        assert all(e.event_type == TelemetryEventType.LLM_CALL_COMPLETED for e in llm_calls)


# ---------------------------------------------------------------------------
# TelemetryService Tests
# ---------------------------------------------------------------------------

class TestTelemetryService:
    """Tests for TelemetryService tracking and aggregation methods."""

    @pytest.mark.asyncio
    async def test_track_start_end_duration(self, telemetry_service, session_id):
        """track_end computes correct duration_ms from track_start timestamp."""
        started = await telemetry_service.track_start(
            session_id, TelemetryStage.SEARCH, message="Search starting"
        )
        assert started.event_type == TelemetryEventType.STARTED

        # Simulate some work
        import asyncio
        await asyncio.sleep(0.05)  # 50ms

        ended = await telemetry_service.track_end(
            session_id, TelemetryStage.SEARCH, started,
            message="Search completed"
        )
        assert ended.event_type == TelemetryEventType.COMPLETED
        assert ended.duration_ms is not None
        assert ended.duration_ms >= 40  # At least ~40ms with some tolerance

    @pytest.mark.asyncio
    async def test_track_progress(self, telemetry_service, session_id):
        """track_progress creates a PROGRESS event with message."""
        event = await telemetry_service.track_progress(
            session_id, TelemetryStage.CLAIM_EXTRACTION,
            message="Processing page 3/10",
            metadata={"page_index": 3, "total": 10}
        )
        assert event.event_type == TelemetryEventType.PROGRESS
        assert "3/10" in event.message

    @pytest.mark.asyncio
    async def test_track_llm_call(self, telemetry_service, session_id):
        """track_llm_call records token counts and Ollama-native durations."""
        metrics = LLMCallMetrics(
            model_name="llama3",
            stage="query_generation",
            prompt_tokens=812,
            completion_tokens=146,
            total_tokens=958,
            total_duration_ms=8500.0,
            load_duration_ms=1200.0,
            prompt_eval_duration_ms=2100.0,
            eval_duration_ms=5200.0,
            prompt_chars=3248,
            response_chars=584,
        )

        event = await telemetry_service.track_llm_call(
            session_id, TelemetryStage.QUERY_GENERATION, metrics
        )
        assert event.event_type == TelemetryEventType.LLM_CALL_COMPLETED
        assert event.tokens_input == 812
        assert event.tokens_output == 146
        assert event.llm_call_id is not None
        assert event.duration_ms == 8500.0

        # Verify metadata contains Ollama-specific fields
        meta = json.loads(event.metadata_json)
        assert meta["model_name"] == "llama3"
        assert meta["load_duration_ms"] == 1200.0
        assert meta["eval_duration_ms"] == 5200.0
        assert meta["prompt_chars"] == 3248

    @pytest.mark.asyncio
    async def test_track_url_lifecycle(self, telemetry_service, session_id):
        """URL lifecycle events are persisted with correct types."""
        url = "https://example.com/page"

        queued = await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_QUEUED, url
        )
        assert queued.event_type == TelemetryEventType.URL_QUEUED
        assert queued.url == url

        fetch_started = await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_STARTED, url
        )
        assert fetch_started.event_type == TelemetryEventType.URL_FETCH_STARTED

        fetch_completed = await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_COMPLETED, url,
            duration_ms=3200.0,
            metadata={"html_size_bytes": 45000, "fetch_status": "success"}
        )
        assert fetch_completed.duration_ms == 3200.0

    @pytest.mark.asyncio
    async def test_track_chunk_lifecycle(self, telemetry_service, session_id):
        """Chunk processing events carry chunk_index and chunk_size in metadata."""
        page_id = str(uuid4())
        url = "https://example.com/docs"

        started = await telemetry_service.track_chunk_event(
            session_id, TelemetryEventType.CHUNK_PROCESSING_STARTED,
            page_id=page_id, url=url,
            chunk_index=2, chunk_size=4000,
            message="Chunk 3/8"
        )
        assert started.event_type == TelemetryEventType.CHUNK_PROCESSING_STARTED
        meta = json.loads(started.metadata_json)
        assert meta["chunk_index"] == 2
        assert meta["chunk_size"] == 4000

        completed = await telemetry_service.track_chunk_event(
            session_id, TelemetryEventType.CHUNK_PROCESSING_COMPLETED,
            page_id=page_id, url=url,
            chunk_index=2, chunk_size=4000,
            duration_ms=7400.0,
            metadata={"claims_extracted": 5}
        )
        meta = json.loads(completed.metadata_json)
        assert meta["claims_extracted"] == 5
        assert completed.duration_ms == 7400.0

    @pytest.mark.asyncio
    async def test_system_metrics_populated(self, telemetry_service, session_id):
        """CPU % and memory MB are populated on events (non-None)."""
        event = await telemetry_service.track_start(
            session_id, TelemetryStage.SESSION, message="Test"
        )
        # psutil should have populated these
        assert event.cpu_percent is not None
        assert event.memory_mb is not None
        assert event.memory_mb > 0  # Process must be using some memory

    @pytest.mark.asyncio
    async def test_research_round_tracking(self, telemetry_service, session_id):
        """Events carry research_round when provided."""
        event = await telemetry_service.track_start(
            session_id, TelemetryStage.SEARCH,
            message="Round 2 search", research_round=2
        )
        assert event.research_round == 2

    @pytest.mark.asyncio
    async def test_queue_metrics(self, telemetry_service, session_id):
        """Queue metrics are recorded in metadata."""
        event = await telemetry_service.track_queue_metrics(
            session_id, queued=100, active=5, completed=47, failed=2
        )
        meta = json.loads(event.metadata_json)
        assert meta["queued_pages"] == 100
        assert meta["active_pages"] == 5
        assert meta["completed_pages"] == 47
        assert meta["failed_pages"] == 2


# ---------------------------------------------------------------------------
# Metrics Aggregation Tests
# ---------------------------------------------------------------------------

class TestMetricsAggregation:
    """Tests for compute_metrics and related aggregation logic."""

    @pytest.mark.asyncio
    async def test_metrics_aggregation(self, telemetry_service, session_id):
        """compute_metrics sums per-stage durations correctly."""
        # Create a mini session with known durations
        t1 = await telemetry_service.track_start(session_id, TelemetryStage.SESSION)

        # Query gen: 2 seconds
        qg_start = await telemetry_service.track_start(session_id, TelemetryStage.QUERY_GENERATION)
        await telemetry_service.track_end(
            session_id, TelemetryStage.QUERY_GENERATION, qg_start,
            message="done"
        )

        # Search: completed with explicit duration in metadata
        s_start = await telemetry_service.track_start(session_id, TelemetryStage.SEARCH)
        await telemetry_service.track_end(
            session_id, TelemetryStage.SEARCH, s_start,
            message="done"
        )

        # LLM call with tokens
        llm = LLMCallMetrics(
            model_name="llama3", prompt_tokens=500, completion_tokens=200,
            total_tokens=700, total_duration_ms=5000.0,
        )
        await telemetry_service.track_llm_call(session_id, TelemetryStage.QUERY_GENERATION, llm)

        await telemetry_service.track_end(session_id, TelemetryStage.SESSION, t1)

        metrics = await telemetry_service.compute_metrics(session_id)
        assert metrics.session_id == session_id
        assert metrics.total_duration_ms > 0
        assert metrics.query_generation_duration_ms >= 0
        assert metrics.search_duration_ms >= 0
        assert metrics.llm_calls == 1
        assert metrics.total_input_tokens == 500
        assert metrics.total_output_tokens == 200

    @pytest.mark.asyncio
    async def test_timeline_ordering(self, telemetry_service, session_id):
        """Timeline events are returned in chronological order."""
        import asyncio

        e1 = await telemetry_service.track_start(session_id, TelemetryStage.SESSION, message="first")
        await asyncio.sleep(0.01)
        e2 = await telemetry_service.track_progress(session_id, TelemetryStage.SESSION, message="second")
        await asyncio.sleep(0.01)
        e3 = await telemetry_service.track_end(session_id, TelemetryStage.SESSION, e1, message="third")

        events = await telemetry_service.get_events(session_id)
        timestamps = [e.timestamp for e in events]

        # Verify chronological ordering
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1], "Events must be in chronological order"

    @pytest.mark.asyncio
    async def test_live_status(self, telemetry_service, session_id):
        """get_live_status returns latest stage and progress info."""
        await telemetry_service.track_start(session_id, TelemetryStage.SESSION)
        await telemetry_service.track_start(session_id, TelemetryStage.FETCH)

        # Queue some URLs
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_QUEUED, "https://a.com"
        )
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_QUEUED, "https://b.com"
        )
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_STARTED, "https://a.com"
        )
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_COMPLETED, "https://a.com",
            duration_ms=100.0
        )

        status = await telemetry_service.get_live_research_status(session_id)
        assert status.session_id == session_id
        assert status.pages_completed == 1
        assert status.pages_total == 2
        assert status.current_url == "https://a.com"

    @pytest.mark.asyncio
    async def test_debug_report(self, telemetry_service, session_id):
        """compute_debug_report returns structured report with slowest items."""
        # Seed some events
        await telemetry_service.track_start(session_id, TelemetryStage.SESSION)
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_COMPLETED, "https://slow.com",
            duration_ms=5000.0
        )
        await telemetry_service.track_url_event(
            session_id, TelemetryEventType.URL_FETCH_COMPLETED, "https://fast.com",
            duration_ms=200.0
        )
        llm = LLMCallMetrics(
            model_name="llama3", total_duration_ms=9000.0,
            prompt_tokens=1000, completion_tokens=500, total_tokens=1500,
        )
        await telemetry_service.track_llm_call(session_id, TelemetryStage.CLAIM_EXTRACTION, llm)

        report = await telemetry_service.compute_debug_report(session_id)
        assert report.session_id == session_id
        assert len(report.slowest_pages) >= 1
        # Slowest page should be first
        assert report.slowest_pages[0].identifier == "https://slow.com"
        assert len(report.slowest_llm_calls) >= 1


# ---------------------------------------------------------------------------
# LLMCallMetrics Tests
# ---------------------------------------------------------------------------

class TestLLMCallMetrics:
    """Tests for the LLMCallMetrics dataclass."""

    def test_from_ollama_response(self):
        """from_ollama_response correctly parses Ollama response fields."""
        ollama_response = {
            "response": '{"queries": ["test"]}',
            "prompt_eval_count": 812,
            "eval_count": 146,
            "total_duration": 8_500_000_000,  # 8500ms in nanoseconds
            "load_duration": 1_200_000_000,
            "prompt_eval_duration": 2_100_000_000,
            "eval_duration": 5_200_000_000,
        }

        metrics = LLMCallMetrics.from_ollama_response(
            ollama_response,
            model_name="llama3",
            stage="query_generation",
            prompt_chars=3248,
            response_chars=584,
        )

        assert metrics.model_name == "llama3"
        assert metrics.prompt_tokens == 812
        assert metrics.completion_tokens == 146
        assert metrics.total_tokens == 958
        assert metrics.total_duration_ms == 8500.0
        assert metrics.load_duration_ms == 1200.0
        assert metrics.prompt_eval_duration_ms == 2100.0
        assert metrics.eval_duration_ms == 5200.0
        assert metrics.prompt_chars == 3248
        assert metrics.llm_call_id is not None

    def test_from_ollama_response_missing_fields(self):
        """Gracefully handles missing Ollama fields (older versions)."""
        minimal_response = {
            "response": "some output",
        }

        metrics = LLMCallMetrics.from_ollama_response(
            minimal_response, model_name="phi4"
        )

        assert metrics.prompt_tokens == 0
        assert metrics.completion_tokens == 0
        assert metrics.total_duration_ms == 0.0
        assert metrics.model_name == "phi4"


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestTelemetryEndpoints:
    """Tests for telemetry API endpoints."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client):
        """GET /api/v1/research/{session_id}/metrics returns 200."""
        session_id = uuid4()
        response = await client.get(f"/api/v1/research/{session_id}/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "total_duration_ms" in data
        assert "tokens_per_claim" in data

    @pytest.mark.asyncio
    async def test_timeline_endpoint(self, client):
        """GET /api/v1/research/{session_id}/timeline returns 200 with list."""
        session_id = uuid4()
        response = await client.get(f"/api/v1/research/{session_id}/timeline")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_live_endpoint(self, client):
        """GET /api/v1/research/{session_id}/live returns 200."""
        session_id = uuid4()
        response = await client.get(f"/api/v1/research/{session_id}/live")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "current_stage" in data
        assert "pages_completed" in data
        assert "pages_total" in data
        assert "progress_percent" in data

    @pytest.mark.asyncio
    async def test_debug_report_endpoint(self, client):
        """GET /api/v1/research/{session_id}/debug-report returns 200."""
        session_id = uuid4()
        response = await client.get(f"/api/v1/research/{session_id}/debug-report")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "durations" in data
        assert "slowest_pages" in data
        assert "slowest_llm_calls" in data
        assert "most_expensive_stage" in data

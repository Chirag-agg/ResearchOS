import asyncio
import json
import pytest
from uuid import uuid4
from unittest.mock import MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.base import get_utc_now
from app.models.telemetry import (
    TelemetryEvent,
    TelemetryStage,
    TelemetryEventType,
    LiveResearchStatus,
)
from app.services.telemetry import TelemetryBroadcaster, TelemetryService
from tests.conftest import test_async_session_maker
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clean_broadcaster():
    """Provides a fresh TelemetryBroadcaster instance for isolation."""
    broadcaster = TelemetryBroadcaster()
    return broadcaster


@pytest.fixture
def telemetry_service(clean_broadcaster):
    """Provides a TelemetryService using the clean broadcaster."""
    return TelemetryService(
        session_maker=test_async_session_maker,
        broadcaster=clean_broadcaster
    )


async def test_broadcaster_single_subscriber(clean_broadcaster):
    """Test that a single subscriber receives broadcast events."""
    session_id = uuid4()
    q = await clean_broadcaster.subscribe(session_id)

    event = TelemetryEvent(
        session_id=session_id,
        stage=TelemetryStage.SEARCH,
        event_type=TelemetryEventType.STARTED,
        message="Search initialized",
    )

    await clean_broadcaster.broadcast(session_id, event)

    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received.id == event.id
    assert received.message == "Search initialized"


async def test_broadcaster_multiple_subscribers(clean_broadcaster):
    """Test that multiple subscribers to the same session receive the same event."""
    session_id = uuid4()
    q1 = await clean_broadcaster.subscribe(session_id)
    q2 = await clean_broadcaster.subscribe(session_id)

    event = TelemetryEvent(
        session_id=session_id,
        stage=TelemetryStage.FETCH,
        event_type=TelemetryEventType.URL_QUEUED,
        message="Queued page",
    )

    await clean_broadcaster.broadcast(session_id, event)

    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    assert r1.id == event.id
    assert r2.id == event.id


async def test_broadcaster_disconnect_cleanup(clean_broadcaster):
    """Test that unsubscribing cleans up the broadcaster state."""
    session_id = uuid4()
    q1 = await clean_broadcaster.subscribe(session_id)
    q2 = await clean_broadcaster.subscribe(session_id)

    assert session_id in clean_broadcaster._subscribers
    assert len(clean_broadcaster._subscribers[session_id]) == 2

    await clean_broadcaster.unsubscribe(session_id, q1)
    assert len(clean_broadcaster._subscribers[session_id]) == 1

    await clean_broadcaster.unsubscribe(session_id, q2)
    assert session_id not in clean_broadcaster._subscribers


async def test_live_status_calculation(telemetry_service):
    """Test that get_live_research_status computes fields and stage-bound progress properly."""
    session_id = uuid4()

    # Initial empty status
    status = await telemetry_service.get_live_research_status(session_id)
    assert status.session_id == session_id
    assert status.progress_percent == 0.0

    # Query generation
    await telemetry_service.track_start(session_id, TelemetryStage.QUERY_GENERATION)
    status = await telemetry_service.get_live_research_status(session_id)
    assert status.current_stage == "query_generation"
    assert status.progress_percent == 10.0

    # Search
    await telemetry_service.track_start(session_id, TelemetryStage.SEARCH)
    status = await telemetry_service.get_live_research_status(session_id)
    assert status.current_stage == "search"
    assert status.progress_percent == 20.0

    # Fetch with 2 pages
    await telemetry_service.track_url_event(session_id, TelemetryEventType.URL_QUEUED, "https://page1.com")
    await telemetry_service.track_url_event(session_id, TelemetryEventType.URL_QUEUED, "https://page2.com")
    await telemetry_service.track_start(session_id, TelemetryStage.FETCH)
    await telemetry_service.track_url_event(session_id, TelemetryEventType.URL_FETCH_COMPLETED, "https://page1.com")
    
    status = await telemetry_service.get_live_research_status(session_id)
    assert status.pages_total == 2
    assert status.pages_completed == 1
    assert status.current_stage == "fetch"
    # 20.0 + (1 / 2) * 30.0 = 35.0%
    assert status.progress_percent == 35.0

    # Claim extraction page 1/1
    await telemetry_service.track_start(session_id, TelemetryStage.CLAIM_EXTRACTION)
    await telemetry_service.track_progress(
        session_id, TelemetryStage.CLAIM_EXTRACTION, message="Page 1/1: extraction"
    )
    # Chunk processing completed (extract 3 claims)
    await telemetry_service.track_chunk_event(
        session_id, TelemetryEventType.CHUNK_PROCESSING_COMPLETED,
        page_id=str(uuid4()), url="https://page1.com", chunk_index=0, chunk_size=1000,
        message="Chunk 1/1", metadata={"claims_extracted": 3}
    )
    status = await telemetry_service.get_live_research_status(session_id)
    assert status.claims_extracted == 3
    # 50.0 + (1/1) * 30.0 = 80.0%
    assert status.progress_percent == 80.0

    # Validation
    await telemetry_service.track_start(session_id, TelemetryStage.VALIDATION)
    # Validate 2 out of 3 claims
    await telemetry_service.track_progress(session_id, TelemetryStage.VALIDATION, "Claim 1/3 supported")
    await telemetry_service.track_progress(session_id, TelemetryStage.VALIDATION, "Claim 2/3 unsupported")

    status = await telemetry_service.get_live_research_status(session_id)
    assert status.validated_claims == 2
    # 80.0 + (2 / 3) * 20.0 = 93.3%
    assert status.progress_percent == 93.3


async def test_live_snapshot_endpoint(client, telemetry_service):
    """Test the GET /api/v1/research/{session_id}/live endpoint."""
    session_id = uuid4()
    # Override the app state telemetry service broadcaster for integration
    app.state.telemetry_service.broadcaster = telemetry_service.broadcaster

    # Seed an event
    await telemetry_service.track_start(session_id, TelemetryStage.QUERY_GENERATION)

    response = await client.get(f"/api/v1/research/{session_id}/live")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session_id)
    assert data["current_stage"] == "query_generation"
    assert data["progress_percent"] == 10.0


async def test_sse_streaming_endpoint(client, telemetry_service):
    """Test the GET /api/v1/research/{session_id}/stream Server-Sent Events endpoint."""
    session_id = uuid4()
    app.state.telemetry_service.broadcaster = telemetry_service.broadcaster
    
    async def trigger_events():
        # Delay slightly to allow subscriber connection
        await asyncio.sleep(0.1)
        await telemetry_service.track_start(session_id, TelemetryStage.QUERY_GENERATION, message="SSE test event")

    # Start event trigger in background
    trigger_task = asyncio.create_task(trigger_events())

    # Read stream using client with once=true to avoid test hang
    events_received = []
    async with client.stream("GET", f"/api/v1/research/{session_id}/stream?once=true") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        # Read the first event
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                events_received.append(payload)
                break  # Exit after receiving the event

    await trigger_task

    assert len(events_received) == 1
    event_payload = events_received[0]
    assert event_payload["stage"] == "query_generation"
    assert event_payload["event_type"] == "started"
    assert event_payload["message"] == "SSE test event"
    assert event_payload["progress_percent"] == 10.0

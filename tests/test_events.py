import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.events.bus import EventBus
from app.events.logger import EventLogger
from app.models.event import EventType, ResearchEvent
from app.models.session import SessionStatus
from app.repositories.event import EventRepository
from app.repositories.session import SessionRepository
from tests.conftest import test_async_session_maker

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


# --- EventBus Unit Tests ---

async def test_event_bus_publish_basic():
    """
    Tests that publishing an event returns a ResearchEvent with correct fields.
    """
    bus = EventBus()
    session_id = uuid4()

    event = await bus.publish(
        EventType.SESSION_CREATED,
        session_id,
        {"question": "Test question"},
    )

    assert event.session_id == session_id
    assert event.event_type == EventType.SESSION_CREATED
    assert event.payload_json is not None

    payload = json.loads(event.payload_json)
    assert payload["question"] == "Test question"


async def test_event_bus_subscriber_called():
    """
    Tests that a subscriber callback is invoked when an event is published.
    """
    bus = EventBus()
    handler = AsyncMock()
    bus.subscribe(EventType.SESSION_CREATED, handler)

    session_id = uuid4()
    await bus.publish(EventType.SESSION_CREATED, session_id, {"test": True})

    handler.assert_called_once()
    event_arg = handler.call_args[0][0]
    assert isinstance(event_arg, ResearchEvent)
    assert event_arg.event_type == EventType.SESSION_CREATED


async def test_event_bus_multiple_subscribers():
    """
    Tests that multiple subscribers all receive the same event.
    """
    bus = EventBus()
    handler_a = AsyncMock()
    handler_b = AsyncMock()
    handler_c = AsyncMock()

    bus.subscribe(EventType.SEARCH_STARTED, handler_a)
    bus.subscribe(EventType.SEARCH_STARTED, handler_b)
    bus.subscribe(EventType.SEARCH_STARTED, handler_c)

    session_id = uuid4()
    await bus.publish(EventType.SEARCH_STARTED, session_id, {"query_count": 5})

    handler_a.assert_called_once()
    handler_b.assert_called_once()
    handler_c.assert_called_once()

    # All three received the same event
    for handler in [handler_a, handler_b, handler_c]:
        event_arg = handler.call_args[0][0]
        assert event_arg.event_type == EventType.SEARCH_STARTED


async def test_event_bus_subscribe_all():
    """
    Tests that subscribe_all registers a callback for every event type.
    """
    bus = EventBus()
    handler = AsyncMock()
    bus.subscribe_all(handler)

    session_id = uuid4()

    # Publish different event types
    await bus.publish(EventType.SESSION_CREATED, session_id)
    await bus.publish(EventType.QUERY_GENERATION_STARTED, session_id)
    await bus.publish(EventType.SEARCH_COMPLETED, session_id)

    assert handler.call_count == 3


async def test_event_bus_subscriber_isolation():
    """
    Tests that a failing subscriber does not prevent other subscribers
    from receiving the event.
    """
    bus = EventBus()

    failing_handler = AsyncMock(side_effect=RuntimeError("Subscriber crashed"))
    surviving_handler = AsyncMock()

    bus.subscribe(EventType.SESSION_CREATED, failing_handler)
    bus.subscribe(EventType.SESSION_CREATED, surviving_handler)

    session_id = uuid4()
    # Should NOT raise despite failing subscriber
    event = await bus.publish(EventType.SESSION_CREATED, session_id)

    assert event is not None
    failing_handler.assert_called_once()
    surviving_handler.assert_called_once()


async def test_event_bus_no_subscribers():
    """
    Tests that publishing to an event type with no subscribers works fine.
    """
    bus = EventBus()
    session_id = uuid4()

    event = await bus.publish(EventType.CLAIM_EXTRACTION_STARTED, session_id)
    assert event.event_type == EventType.CLAIM_EXTRACTION_STARTED


async def test_event_bus_publish_with_step_id():
    """
    Tests that step_id is correctly attached to published events.
    """
    bus = EventBus()
    session_id = uuid4()
    step_id = uuid4()

    event = await bus.publish(
        EventType.FETCH_STARTED,
        session_id,
        {"url_count": 10},
        step_id=step_id,
    )

    assert event.step_id == step_id


async def test_event_bus_publish_none_payload():
    """
    Tests that publishing with no payload results in payload_json=None.
    """
    bus = EventBus()
    session_id = uuid4()

    event = await bus.publish(EventType.SESSION_CREATED, session_id)
    assert event.payload_json is None


# --- EventRepository Tests ---

async def test_event_repository_create(db_session: AsyncSession):
    """
    Tests that a ResearchEvent can be persisted.
    """
    session_repo = SessionRepository(db_session)
    event_repo = EventRepository(db_session)

    session = await session_repo.create_session("Event test session")

    event = ResearchEvent(
        session_id=session.id,
        event_type=EventType.SESSION_CREATED,
        payload_json=json.dumps({"question": "test"}),
    )
    created = await event_repo.create_event(event)

    assert created.id is not None
    assert created.event_type == EventType.SESSION_CREATED


async def test_event_repository_get_session_events(db_session: AsyncSession):
    """
    Tests chronological retrieval of all events for a session.
    """
    session_repo = SessionRepository(db_session)
    event_repo = EventRepository(db_session)

    session = await session_repo.create_session("Event ordering test")

    # Insert events in order
    for etype in [
        EventType.SESSION_CREATED,
        EventType.QUERY_GENERATION_STARTED,
        EventType.QUERY_GENERATION_COMPLETED,
        EventType.SESSION_COMPLETED,
    ]:
        event = ResearchEvent(
            session_id=session.id,
            event_type=etype,
        )
        await event_repo.create_event(event)

    events = await event_repo.get_session_events(session.id)

    assert len(events) == 4
    assert events[0].event_type == EventType.SESSION_CREATED
    assert events[1].event_type == EventType.QUERY_GENERATION_STARTED
    assert events[2].event_type == EventType.QUERY_GENERATION_COMPLETED
    assert events[3].event_type == EventType.SESSION_COMPLETED


async def test_event_repository_get_events_by_type(db_session: AsyncSession):
    """
    Tests filtering events by type.
    """
    session_repo = SessionRepository(db_session)
    event_repo = EventRepository(db_session)

    session = await session_repo.create_session("Event filter test")

    for etype in [
        EventType.SESSION_CREATED,
        EventType.SEARCH_STARTED,
        EventType.SEARCH_COMPLETED,
        EventType.SEARCH_STARTED,  # Duplicate type
    ]:
        event = ResearchEvent(session_id=session.id, event_type=etype)
        await event_repo.create_event(event)

    search_events = await event_repo.get_events_by_type(
        EventType.SEARCH_STARTED, session_id=session.id
    )
    assert len(search_events) == 2

    session_events = await event_repo.get_events_by_type(
        EventType.SESSION_CREATED, session_id=session.id
    )
    assert len(session_events) == 1


# --- EventLogger Integration Tests ---

async def test_event_logger_persists_event():
    """
    Tests that EventLogger successfully persists an event via its own session.
    """
    logger = EventLogger(session_maker=test_async_session_maker)

    # Create a session first (EventLogger needs a valid FK)
    async with test_async_session_maker() as session:
        session_repo = SessionRepository(session)
        research_session = await session_repo.create_session("Logger test")

    event = ResearchEvent(
        session_id=research_session.id,
        event_type=EventType.SESSION_CREATED,
        payload_json=json.dumps({"question": "Logger test"}),
    )

    # This should persist without error
    await logger.handle_event(event)

    # Verify it was persisted
    async with test_async_session_maker() as session:
        event_repo = EventRepository(session)
        events = await event_repo.get_session_events(research_session.id)
        assert len(events) >= 1
        assert any(e.event_type == EventType.SESSION_CREATED for e in events)


async def test_event_logger_failure_does_not_raise():
    """
    Tests that EventLogger handles persistence failures gracefully.
    """
    logger = EventLogger(session_maker=test_async_session_maker)

    # Create an event with an invalid session_id (FK violation)
    event = ResearchEvent(
        session_id=uuid4(),  # Non-existent session
        event_type=EventType.SESSION_CREATED,
    )

    # Should NOT raise — EventLogger swallows errors
    await logger.handle_event(event)


# --- EventBus + EventLogger Full Pipeline Test ---

async def test_event_bus_with_logger_full_pipeline():
    """
    Tests the full pipeline: EventBus publishes → EventLogger persists → DB has events.
    """
    bus = EventBus()
    logger = EventLogger(session_maker=test_async_session_maker)
    bus.subscribe_all(logger.handle_event)

    # Create a session
    async with test_async_session_maker() as session:
        session_repo = SessionRepository(session)
        research_session = await session_repo.create_session("Full pipeline test")

    # Publish events through the bus
    await bus.publish(
        EventType.SESSION_CREATED, research_session.id,
        {"question": "pipeline test"},
    )
    await bus.publish(
        EventType.QUERY_GENERATION_STARTED, research_session.id,
    )
    await bus.publish(
        EventType.QUERY_GENERATION_COMPLETED, research_session.id,
        {"query_count": 3},
    )

    # Verify all events were persisted
    async with test_async_session_maker() as session:
        event_repo = EventRepository(session)
        events = await event_repo.get_session_events(research_session.id)

        assert len(events) >= 3

        event_types = [e.event_type for e in events]
        assert EventType.SESSION_CREATED in event_types
        assert EventType.QUERY_GENERATION_STARTED in event_types
        assert EventType.QUERY_GENERATION_COMPLETED in event_types


# --- Endpoint Integration Tests ---

async def test_events_endpoint_session_not_found(client):
    """
    Tests that GET /api/v1/sessions/{id}/events returns 404 for non-existent session.
    """
    fake_id = str(uuid4())
    response = await client.get(f"/api/v1/sessions/{fake_id}/events")
    assert response.status_code == 404


async def test_events_endpoint_returns_events(client, db_session: AsyncSession):
    """
    Tests that GET /api/v1/sessions/{id}/events returns persisted events.
    """
    session_repo = SessionRepository(db_session)
    event_repo = EventRepository(db_session)

    session = await session_repo.create_session("Events endpoint test")

    # Insert some events
    for etype in [EventType.SESSION_CREATED, EventType.SEARCH_STARTED]:
        event = ResearchEvent(
            session_id=session.id,
            event_type=etype,
            payload_json=json.dumps({"test": True}),
        )
        await event_repo.create_event(event)

    response = await client.get(f"/api/v1/sessions/{session.id}/events")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session.id)
    assert data["total_events"] == 2
    assert len(data["events"]) == 2

    # Verify event structure
    first_event = data["events"][0]
    assert "event_type" in first_event
    assert "timestamp" in first_event
    assert "payload" in first_event
    assert first_event["payload"]["test"] is True

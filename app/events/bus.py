import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Optional
from uuid import UUID

from app.models.base import get_utc_now
from app.models.event import EventType, ResearchEvent

logger = logging.getLogger(__name__)

# Type alias for subscriber callbacks
EventCallback = Callable[[ResearchEvent], Coroutine[Any, Any, None]]


class EventBus:
    """
    Async-safe, in-memory publish/subscribe event bus for the research pipeline.

    Every research action publishes events through this bus. Subscribers
    (like EventLogger) react to events asynchronously. Multiple subscribers
    can listen to the same event type.

    Usage:
        bus = EventBus()
        bus.subscribe(EventType.SESSION_CREATED, my_handler)
        await bus.publish(EventType.SESSION_CREATED, session_id, {"question": "..."})
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventCallback]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """
        Register a callback for a specific event type.
        Callbacks must be async coroutine functions accepting a ResearchEvent.
        """
        self._subscribers[event_type].append(callback)
        logger.debug(
            f"Subscriber registered for {event_type.value}: "
            f"{getattr(callback, '__qualname__', repr(callback))}"
        )

    def subscribe_all(self, callback: EventCallback) -> None:
        """
        Register a callback for every event type.
        Useful for cross-cutting concerns like logging and persistence.
        """
        for event_type in EventType:
            self.subscribe(event_type, callback)
        logger.info(
            f"Subscriber registered for ALL event types: "
            f"{getattr(callback, '__qualname__', repr(callback))}"
        )

    async def publish(
        self,
        event_type: EventType,
        session_id: UUID,
        payload: Optional[dict] = None,
        step_id: Optional[UUID] = None,
    ) -> ResearchEvent:
        """
        Publish an event to all registered subscribers.

        Creates a ResearchEvent, serializes the payload to JSON, then
        invokes all subscriber callbacks concurrently via asyncio.gather.
        Subscriber failures are logged but never propagate — publishing
        must not break the research pipeline.

        Returns the created ResearchEvent for caller reference.
        """
        # Serialize payload
        payload_json = json.dumps(payload) if payload else None

        # Create the event object
        event = ResearchEvent(
            session_id=session_id,
            step_id=step_id,
            event_type=event_type,
            payload_json=payload_json,
            created_at=get_utc_now(),
        )

        logger.info(
            f"Event published: {event_type.value} | session={session_id}"
            + (f" | step={step_id}" if step_id else "")
        )

        # Dispatch to all subscribers for this event type
        callbacks = self._subscribers.get(event_type, [])
        if callbacks:
            tasks = []
            for callback in callbacks:
                tasks.append(self._safe_invoke(callback, event))
            await asyncio.gather(*tasks)

        return event

    @staticmethod
    async def _safe_invoke(callback: EventCallback, event: ResearchEvent) -> None:
        """
        Invoke a subscriber callback with error isolation.
        A failing subscriber must never crash the publisher.
        """
        try:
            await callback(event)
        except Exception as e:
            logger.error(
                f"Subscriber {getattr(callback, '__qualname__', repr(callback))} "
                f"failed for {event.event_type.value}: {e}",
                exc_info=True,
            )

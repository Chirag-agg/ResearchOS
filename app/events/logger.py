import logging
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.event import ResearchEvent
from app.repositories.event import EventRepository

logger = logging.getLogger(__name__)


class EventLogger:
    """
    Subscriber that automatically persists every published event to SQLite.

    Uses its own database session (not the request-scoped one) since event
    persistence is a background concern that outlives individual HTTP requests.
    Subscribing this to EventBus.subscribe_all() ensures every single event
    gets recorded — forming a complete audit trail.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker

    async def handle_event(self, event: ResearchEvent) -> None:
        """
        Callback invoked by EventBus for every published event.
        Opens a fresh DB session, persists the event, and closes cleanly.
        """
        if event.session_id is None:
            logger.debug(
                f"Skipping database persistence for event {event.event_type.value} "
                "because it has no active session association."
            )
            return

        try:
            async with self._session_maker() as session:
                repo = EventRepository(session)
                await repo.create_event(event)
                logger.debug(
                    f"Event persisted: {event.event_type.value} | "
                    f"session={event.session_id}"
                )
        except Exception as e:
            # Log but never propagate — the research pipeline must not break
            # because event persistence failed.
            logger.error(
                f"Failed to persist event {event.event_type.value}: {e}",
                exc_info=True,
            )

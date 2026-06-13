import logging
import asyncio
import json
import re
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import List

from app.models.telemetry import (
    TelemetryEventRead,
    ResearchMetrics,
    ResearchLiveStatus,
    DebugReport,
    LiveResearchStatus,
    TelemetryEventType,
    TelemetryStage,
)
from app.services.telemetry import TelemetryService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])


def _get_telemetry(request: Request) -> TelemetryService:
    """Retrieve TelemetryService from app state."""
    telemetry = getattr(request.app.state, "telemetry_service", None)
    if telemetry is None:
        raise HTTPException(status_code=503, detail="Telemetry service not initialized")
    return telemetry


@router.get(
    "/research/{session_id}/metrics",
    response_model=ResearchMetrics,
    summary="Get aggregated research metrics",
    description="Returns aggregated per-stage durations, token usage, page/claim counts, "
                "efficiency metrics (tokens_per_claim), and identifies the most expensive stage.",
)
async def get_research_metrics(
    session_id: UUID,
    telemetry: TelemetryService = Depends(_get_telemetry),
):
    """
    GET /api/v1/research/{session_id}/metrics

    Returns aggregated ResearchMetrics for a session.
    """
    try:
        metrics = await telemetry.compute_metrics(session_id)
        return metrics
    except Exception as e:
        logger.error(f"Failed to compute metrics for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Metrics computation failed: {e}")


@router.get(
    "/research/{session_id}/timeline",
    response_model=List[TelemetryEventRead],
    summary="Get chronological telemetry timeline",
    description="Returns all telemetry events for a session in chronological order. "
                "Includes URL lifecycle, chunk processing, LLM calls, and stage transitions.",
)
async def get_research_timeline(
    session_id: UUID,
    telemetry: TelemetryService = Depends(_get_telemetry),
):
    """
    GET /api/v1/research/{session_id}/timeline

    Returns chronological list of TelemetryEventRead objects.
    """
    try:
        events = await telemetry.get_events(session_id)
        return [
            TelemetryEventRead(
                id=e.id,
                session_id=e.session_id,
                timestamp=e.timestamp,
                stage=e.stage,
                event_type=e.event_type,
                message=e.message,
                duration_ms=e.duration_ms,
                tokens_input=e.tokens_input,
                tokens_output=e.tokens_output,
                url=e.url,
                page_id=e.page_id,
                query_id=e.query_id,
                claim_id=e.claim_id,
                llm_call_id=e.llm_call_id,
                research_round=e.research_round,
                metadata_json=e.metadata_json,
                cpu_percent=e.cpu_percent,
                memory_mb=e.memory_mb,
            )
            for e in events
        ]
    except Exception as e:
        logger.error(f"Failed to get timeline for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Timeline retrieval failed: {e}")


@router.get(
    "/research/{session_id}/live",
    response_model=LiveResearchStatus,
    summary="Get current research status",
    description="Returns the current stage, progress percentage, pages processed/remaining, "
                "current URL, CPU/RAM usage for a running session.",
)
async def get_research_live_status(
    session_id: UUID,
    telemetry: TelemetryService = Depends(_get_telemetry),
):
    """
    GET /api/v1/research/{session_id}/live

    Returns current LiveResearchStatus.
    """
    try:
        status = await telemetry.get_live_research_status(session_id)
        return status
    except Exception as e:
        logger.error(f"Failed to get live status for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Live status retrieval failed: {e}")


@router.get(
    "/research/{session_id}/stream",
    summary="Stream live research telemetry events",
    description="Streams research pipeline progress updates in real time using Server-Sent Events (SSE).",
)
async def stream_research_telemetry(
    session_id: UUID,
    once: bool = False,
    telemetry: TelemetryService = Depends(_get_telemetry),
):
    """
    GET /api/v1/research/{session_id}/stream

    Streams live telemetry events via SSE.
    """
    async def event_generator():
        q = await telemetry.broadcaster.subscribe(session_id)
        
        # Local progress counters to avoid DB lock/deadlock during streaming
        pages_total = 0
        pages_completed = 0
        claims_extracted = 0
        validated_claims = 0
        current_extraction_page = 0
        total_extraction_pages = 0

        try:
            while True:
                # Wait for next event broadcasted for this session
                event = await q.get()
                
                # Update local progress counters from event data
                if event.event_type == TelemetryEventType.URL_QUEUED:
                    pages_total += 1
                elif event.event_type == TelemetryEventType.URL_FETCH_COMPLETED:
                    if event.metadata_json:
                        try:
                            meta = json.loads(event.metadata_json)
                            if meta.get("fetch_status") == "success":
                                pages_completed += 1
                        except Exception:
                            pages_completed += 1
                    else:
                        pages_completed += 1
                elif event.event_type == TelemetryEventType.CHUNK_PROCESSING_COMPLETED:
                    if event.metadata_json:
                        try:
                            meta = json.loads(event.metadata_json)
                            claims_extracted += meta.get("claims_extracted", 0)
                        except Exception:
                            pass
                elif event.stage == TelemetryStage.VALIDATION and event.event_type == TelemetryEventType.PROGRESS:
                    validated_claims += 1
                elif event.stage == TelemetryStage.CLAIM_EXTRACTION and event.event_type == TelemetryEventType.PROGRESS:
                    if event.message:
                        match = re.search(r"Page (\d+)/(\d+)", event.message)
                        if match:
                            current_extraction_page = int(match.group(1))
                            total_extraction_pages = int(match.group(2))

                # Calculate progress percent locally
                progress_percent = 0.0
                stage = event.stage
                if stage == TelemetryStage.QUERY_GENERATION:
                    progress_percent = 10.0
                elif stage == TelemetryStage.SEARCH:
                    progress_percent = 20.0
                elif stage == TelemetryStage.FETCH:
                    pct = 20.0
                    if pages_total > 0:
                        pct += (pages_completed / pages_total) * 30.0
                    progress_percent = round(pct, 1)
                elif stage == TelemetryStage.CLAIM_EXTRACTION:
                    pct = 50.0
                    if total_extraction_pages > 0:
                        pct += (current_extraction_page / total_extraction_pages) * 30.0
                    progress_percent = round(pct, 1)
                elif stage == TelemetryStage.VALIDATION:
                    pct = 80.0
                    if claims_extracted > 0:
                        pct += (validated_claims / claims_extracted) * 20.0
                    progress_percent = round(pct, 1)
                elif stage == TelemetryStage.SESSION:
                    if event.event_type == TelemetryEventType.COMPLETED:
                        progress_percent = 100.0
                    elif event.event_type == TelemetryEventType.FAILED:
                        progress_percent = 100.0
                    else:
                        progress_percent = 0.0
                else:
                    if stage == TelemetryStage.KNOWLEDGE_BUILDING:
                        progress_percent = 90.0
                    elif stage == TelemetryStage.GAP_DISCOVERY:
                        progress_percent = 93.0
                    elif stage == TelemetryStage.PLANNING:
                        progress_percent = 95.0
                    elif stage == TelemetryStage.REPORT_GENERATION:
                        progress_percent = 98.0
                    else:
                        progress_percent = 100.0
                
                # Format payload
                payload = telemetry.format_stream_payload(event, progress_percent)
                
                yield f"data: {json.dumps(payload)}\n\n"
                
                if once:
                    break
        except asyncio.CancelledError:
            logger.info(f"SSE stream client cancelled for session {session_id}.")
            raise
        except Exception as e:
            logger.error(f"Error in SSE stream for session {session_id}: {e}")
            raise
        finally:
            await telemetry.broadcaster.unsubscribe(session_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get(
    "/research/{session_id}/debug-report",
    response_model=DebugReport,
    summary="Get full debug report",
    description="Returns a comprehensive debug report: per-stage durations, token usage, "
                "slowest pages, slowest queries, slowest LLM calls, most expensive stage, "
                "and efficiency metrics (tokens_per_claim, tokens_per_validated_claim).",
)
async def get_debug_report(
    session_id: UUID,
    telemetry: TelemetryService = Depends(_get_telemetry),
):
    """
    GET /api/v1/research/{session_id}/debug-report

    Returns the debug report you'll use constantly.
    """
    try:
        report = await telemetry.compute_debug_report(session_id)
        return report
    except Exception as e:
        logger.error(f"Failed to compute debug report for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Debug report computation failed: {e}")

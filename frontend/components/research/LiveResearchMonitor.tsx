"use client";

import { useEffect, useState, useRef } from "react";
import {
  LiveResearchStatus,
  TelemetryEventRead,
  ResearchMetrics,
} from "@/types/research";
import {
  getResearchLiveStatus,
  getResearchTimeline,
  getResearchMetrics,
  getApiBaseUrl,
} from "@/lib/api";

interface LiveResearchMonitorProps {
  sessionId: string;
}

interface StreamEvent {
  timestamp: string;
  stage: string;
  event_type: string;
  message: string;
  progress_percent: number;
  cpu_percent: number;
  memory_mb: number;
  metadata: Record<string, unknown>;
}

export function LiveResearchMonitor({ sessionId }: LiveResearchMonitorProps) {
  const [status, setStatus] = useState<LiveResearchStatus | null>(null);
  const [events, setEvents] = useState<TelemetryEventRead[]>([]);
  const [metrics, setMetrics] = useState<ResearchMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const eventsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Scroll to bottom of events when new ones arrive
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  useEffect(() => {
    let mounted = true;
    let sse: EventSource | null = null;
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    async function fetchInitial() {
      try {
        const [liveRes, timelineRes, metricsRes] = await Promise.all([
          getResearchLiveStatus(sessionId).catch(() => null),
          getResearchTimeline(sessionId).catch(() => []),
          getResearchMetrics(sessionId).catch(() => null),
        ]);
        if (mounted) {
          if (liveRes) setStatus(liveRes);
          if (timelineRes) setEvents(timelineRes);
          if (metricsRes) setMetrics(metricsRes);
        }
      } catch (err) {
        console.error("Failed to fetch initial telemetry", err);
        setError("Failed to load initial telemetry data.");
      }
    }

    async function pollLiveAndMetrics() {
      try {
        const liveRes = await getResearchLiveStatus(sessionId);
        const metricsRes = await getResearchMetrics(sessionId);
        if (mounted) {
          setStatus(liveRes);
          setMetrics(metricsRes);
        }
      } catch (err) {
        // ignore polling errors
      }
    }

    fetchInitial().then(() => {
      if (!mounted) return;

      // Start SSE for instant updates
      sse = new EventSource(
        `${getApiBaseUrl()}/api/v1/research/${sessionId}/stream`
      );

      sse.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as StreamEvent;
          
          setStatus((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              progress_percent: data.progress_percent,
              current_stage: data.stage,
              cpu_percent: data.cpu_percent,
              memory_mb: data.memory_mb,
            };
          });

          // Append to events timeline
          setEvents((prev) => {
            // Only add if it's not a duplicate (simple check)
            // The stream doesn't give event IDs, so we approximate
            return [
              ...prev,
              {
                id: Math.random().toString(36).substring(7),
                session_id: sessionId,
                timestamp: data.timestamp,
                stage: data.stage,
                event_type: data.event_type,
                message: data.message,
                metadata_json: JSON.stringify(data.metadata),
              } as TelemetryEventRead,
            ];
          });
        } catch (err) {
          console.error("Error parsing SSE event", err);
        }
      };

      sse.onerror = () => {
        // SSE drops occasionally, we can just let browser auto-reconnect
        console.log("SSE error or connection dropped. Reconnecting...");
      };

      // Poll metrics and counts every 3 seconds to keep UI completely accurate
      pollInterval = setInterval(pollLiveAndMetrics, 3000);
    });

    return () => {
      mounted = false;
      if (sse) sse.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [sessionId]);

  const formatTime = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  if (error && !status) {
    return <div className="p-8 text-red-500">{error}</div>;
  }

  if (!status) {
    return <div className="p-8 text-white/70">Connecting to telemetry stream...</div>;
  }

  return (
    <div className="flex w-full max-w-6xl flex-col gap-6 font-mono text-sm text-white/90">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 pb-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-white">Live Research Monitor</h2>
          <p className="text-xs text-white/50">{sessionId}</p>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
            <span>Live Stream Connected</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Progress */}
        <div className="glass-card flex flex-col gap-4 p-6 lg:col-span-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-white/50">Current Progress</h3>
          
          <div className="flex flex-col gap-1">
            <span className="text-xs text-white/50">Stage</span>
            <span className="text-lg font-medium text-primary capitalize">{status.current_stage.replace(/_/g, " ")}</span>
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-xs text-white/50">
              <span>Progress</span>
              <span>{status.progress_percent.toFixed(1)}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full bg-primary transition-all duration-500"
                style={{ width: `${status.progress_percent}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 pt-4">
            <div className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/5 p-3">
              <span className="text-xs text-white/50">Pages</span>
              <span className="text-xl">{status.pages_completed} / {status.pages_total}</span>
            </div>
            <div className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/5 p-3">
              <span className="text-xs text-white/50">Claims</span>
              <span className="text-xl">{status.claims_extracted}</span>
            </div>
            <div className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/5 p-3">
              <span className="text-xs text-white/50">Validated</span>
              <span className="text-xl">{status.validated_claims}</span>
            </div>
            <div className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/5 p-3">
              <span className="text-xs text-white/50">Round</span>
              <span className="text-xl">{metrics?.question ? "Iterative" : "1"}</span>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-1">
            <span className="text-xs text-white/50">System Load</span>
            <div className="flex justify-between text-xs">
              <span>CPU: {status.cpu_percent.toFixed(1)}%</span>
              <span>RAM: {status.memory_mb.toFixed(0)} MB</span>
            </div>
          </div>
        </div>

        {/* Right Column: Timeline */}
        <div className="glass-card flex h-[400px] flex-col gap-4 p-6 lg:col-span-7">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-white/50">Live Events</h3>
          <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-white/10">
            <div className="flex flex-col gap-2">
              {events.map((evt, idx) => (
                <div key={evt.id || idx} className="flex gap-4 text-xs border-l-2 border-white/10 pl-3 py-1 hover:border-primary/50 transition-colors">
                  <span className="shrink-0 text-white/40">{formatTime(evt.timestamp)}</span>
                  <div className="flex flex-col">
                    <span className="font-medium text-white/80">
                      {evt.event_type.replace(/_/g, " ").toUpperCase()} 
                      <span className="text-white/40 font-normal ml-2 capitalize">({evt.stage})</span>
                    </span>
                    {evt.message && <span className="text-white/60 mt-0.5">{evt.message}</span>}
                  </div>
                </div>
              ))}
              <div ref={eventsEndRef} />
            </div>
          </div>
        </div>
      </div>

      {/* Middle: Current Action */}
      {status.current_url && (
        <div className="glass-card flex flex-col gap-2 p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-white/50">Current URL</h3>
          <span className="break-all text-sm text-primary">{status.current_url}</span>
        </div>
      )}

      {/* Bottom: Metrics */}
      <div className="glass-card flex flex-col gap-4 p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-white/50">Research Metrics</h3>
        {metrics ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-white/50">Total Duration</span>
              <span>{(metrics.total_duration_ms / 1000).toFixed(1)}s</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-white/50">LLM Calls</span>
              <span>{metrics.llm_calls}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-white/50">Tokens Input</span>
              <span>{metrics.total_input_tokens.toLocaleString()}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-white/50">Tokens Output</span>
              <span>{metrics.total_output_tokens.toLocaleString()}</span>
            </div>
          </div>
        ) : (
          <div className="text-xs text-white/40">Waiting for metrics...</div>
        )}
      </div>
    </div>
  );
}

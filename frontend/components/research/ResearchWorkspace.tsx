"use client";

import { useEffect, useMemo, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { LiveResearchMonitor } from "./LiveResearchMonitor";
import { SourceSearch } from "./sources/SourceSearch";
import { SourceFilters, type SourceFilterId } from "./sources/SourceFilters";
import { SourceMetrics } from "./sources/SourceMetrics";
import { SourceList } from "./sources/SourceList";
import { SourceDetails } from "./sources/SourceDetails";
import { ReasoningWorkspace } from "./reasoning/ReasoningWorkspace";
import { getResearchKnowledge, getResearchMetrics, getResearchSources, getResearchTimeline } from "@/lib/api";
import type { TelemetryEventRead, ResearchMetrics } from "@/types/research";
import type { KnowledgeGraphResponse, ResearchSourceRead } from "@/types/workspace";
import dynamic from "next/dynamic";

const KnowledgeGraphWorkspace = dynamic(() => import("./knowledge/KnowledgeGraphWorkspace").then((m) => m.KnowledgeGraphWorkspace), { ssr: false });
import { cn } from "@/lib/utils";

type WorkspaceTab = "overview" | "sources" | "knowledge" | "reasoning" | "timeline";

interface ResearchWorkspaceProps {
    sessionId: string;
}

function TabButton({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                "rounded-full border px-4 py-2 text-sm font-medium transition-colors",
                active
                    ? "border-primary/60 bg-primary/15 text-white"
                    : "border-white/10 bg-white/5 text-white/65 hover:border-white/20 hover:bg-white/10"
            )}
        >
            {children}
        </button>
    );
}

export function ResearchWorkspace({ sessionId }: ResearchWorkspaceProps) {
    const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");
    const [sources, setSources] = useState<ResearchSourceRead[]>([]);
    const [knowledge, setKnowledge] = useState<KnowledgeGraphResponse | null>(null);
    const [timeline, setTimeline] = useState<TelemetryEventRead[]>([]);
    const [metrics, setMetrics] = useState<ResearchMetrics | null>(null);
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState<SourceFilterId>("all");
    const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let mounted = true;

        async function loadWorkspace() {
            try {
                const [sourcesRes, knowledgeRes, timelineRes, metricsRes] = await Promise.all([
                    getResearchSources(sessionId).catch(() => ({ session_id: sessionId, sources: [] })),
                    getResearchKnowledge(sessionId).catch(() => ({ nodes: [], edges: [] })),
                    getResearchTimeline(sessionId).catch(() => []),
                    getResearchMetrics(sessionId).catch(() => null),
                ]);

                if (!mounted) return;

                const nextSources = sourcesRes?.sources ?? [];

                setSources(nextSources);
                setKnowledge(knowledgeRes);
                setTimeline(timelineRes);
                setMetrics(metricsRes);
                setSelectedSourceId((current) => current ?? nextSources[0]?.page_id ?? null);
            } catch (loadError) {
                console.error("Failed to load research workspace", loadError);
                if (mounted) setError("Failed to load research workspace data.");
            }
        }

        loadWorkspace();
        const interval = setInterval(loadWorkspace, 5000);

        return () => {
            mounted = false;
            clearInterval(interval);
        };
    }, [sessionId]);

    const filteredSources = useMemo(() => {
        const query = search.trim().toLowerCase();

        return sources.filter((source) => {
            const matchesQuery =
                !query ||
                source.title.toLowerCase().includes(query) ||
                source.domain.toLowerCase().includes(query) ||
                source.url.toLowerCase().includes(query) ||
                source.key_claims.some((claim) => claim.toLowerCase().includes(query));

            const matchesFilter = (() => {
                if (filter === "all") return true;
                if (filter === "low") return source.quality_score < 0.5;
                if (filter === "high") return source.quality_score >= 0.75;
                return source.source_type === filter;
            })();

            return matchesQuery && matchesFilter;
        });
    }, [sources, search, filter]);

    useEffect(() => {
        if (!selectedSourceId && filteredSources.length > 0) {
            setSelectedSourceId(filteredSources[0].page_id);
        }
    }, [filteredSources, selectedSourceId]);

    const selectedSource = filteredSources.find((source) => source.page_id === selectedSourceId) ?? filteredSources[0] ?? sources[0] ?? null;
    const knowledgeNodeMap = useMemo(
        () => new Map((knowledge?.nodes ?? []).map((node) => [node.id, node])),
        [knowledge]
    );

    const analyzedCount = sources.filter((source) => source.analysis_status === "analyzed").length;
    const highQualityCount = sources.filter((source) => source.quality_score >= 0.75).length;
    const lowQualityCount = sources.filter((source) => source.quality_score < 0.5).length;

    if (error) {
        return <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-6 text-red-200">{error}</div>;
    }

    return (
        <div className="w-full max-w-[1400px] space-y-6 text-white">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-white/45">
                        <LayoutGrid className="h-4 w-4" /> Research Workspace
                    </div>
                    <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Session {sessionId}</h1>
                    <p className="mt-2 max-w-2xl text-sm text-white/55">
                        Inspect live progress, sources, extracted knowledge, and the event timeline without leaving the workspace.
                    </p>
                </div>

                <div className="flex flex-wrap gap-2">
                    <TabButton active={activeTab === "overview"} onClick={() => setActiveTab("overview")}>Overview</TabButton>
                    <TabButton active={activeTab === "sources"} onClick={() => setActiveTab("sources")}>Sources</TabButton>
                    <TabButton active={activeTab === "knowledge"} onClick={() => setActiveTab("knowledge")}>Knowledge</TabButton>
                    <TabButton active={activeTab === "reasoning"} onClick={() => setActiveTab("reasoning")}>Reasoning</TabButton>
                    <TabButton active={activeTab === "timeline"} onClick={() => setActiveTab("timeline")}>Timeline</TabButton>
                </div>
            </div>

            {activeTab === "overview" && <LiveResearchMonitor sessionId={sessionId} />}

            {activeTab === "sources" && (
                <div className="space-y-6">
                    <SourceMetrics
                        total={sources.length}
                        analyzed={analyzedCount}
                        highQuality={highQualityCount}
                        lowQuality={lowQualityCount}
                    />

                    <div className="grid gap-6 xl:grid-cols-12">
                        <div className="space-y-4 xl:col-span-5">
                            <SourceSearch value={search} onChange={setSearch} />
                            <SourceFilters value={filter} onChange={setFilter} />
                            <div className="max-h-[72vh] overflow-y-auto pr-1">
                                <SourceList
                                    sources={filteredSources}
                                    selectedSourceId={selectedSource?.page_id ?? null}
                                    onSelectSource={setSelectedSourceId}
                                />
                            </div>
                        </div>

                        <div className="xl:col-span-7">
                            {selectedSource ? (
                                <SourceDetails source={selectedSource} />
                            ) : (
                                <div className="rounded-3xl border border-white/10 bg-white/5 p-10 text-center text-white/60 backdrop-blur-md">
                                    No source matches your current search and filter.
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {activeTab === "knowledge" && (
                <div className="space-y-6">
                    {knowledge ? (
                        <KnowledgeGraphWorkspace sessionId={sessionId} knowledge={knowledge} sources={sources} />
                    ) : (
                        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-white/60">No knowledge graph has been built yet for this session.</div>
                    )}
                </div>
            )}

            {activeTab === "reasoning" && <ReasoningWorkspace sessionId={sessionId} />}

            {activeTab === "timeline" && (
                <div className="glass-card p-6">
                    <h2 className="text-lg font-semibold text-white">Timeline</h2>
                    <div className="mt-4 max-h-[75vh] overflow-y-auto pr-2">
                        <div className="flex flex-col gap-3">
                            {timeline.length ? timeline.map((event) => (
                                <div key={event.id} className="flex gap-4 rounded-2xl border border-white/10 bg-white/5 p-4">
                                    <div className="shrink-0 text-xs text-white/45">{new Date(event.timestamp).toLocaleTimeString()}</div>
                                    <div>
                                        <div className="text-sm font-medium text-white">{event.event_type.replace(/_/g, " ")}</div>
                                        <div className="text-sm text-white/60">{event.message}</div>
                                    </div>
                                </div>
                            )) : (
                                <div className="text-sm text-white/55">No events have been recorded yet.</div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
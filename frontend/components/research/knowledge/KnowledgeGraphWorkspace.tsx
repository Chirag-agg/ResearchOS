"use client";

import { useEffect, useMemo, useState } from "react";
import {
    Background,
    Controls,
    Handle,
    MarkerType,
    Position,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
    type Edge,
    type Node,
    type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { Search, ZoomIn, Maximize2, RotateCcw, CircleDot } from "lucide-react";
import { cn } from "@/lib/utils";
import type { KnowledgeEdgeRead, KnowledgeGraphResponse, KnowledgeNodeRead, ResearchSourceRead } from "@/types/workspace";

const NODE_WIDTH = 240;
const NODE_HEIGHT = 104;

type KnowledgeNodeType =
    | "Concept"
    | "Person"
    | "Organization"
    | "Technology"
    | "Paper"
    | "Method"
    | "Dataset"
    | "Benchmark";

type Selection =
    | { kind: "node"; id: string }
    | { kind: "edge"; id: string }
    | null;

interface KnowledgeGraphWorkspaceProps {
    sessionId: string;
    knowledge: KnowledgeGraphResponse;
    sources: ResearchSourceRead[];
}

interface GraphNodeData {
    node: KnowledgeNodeRead;
    nodeType: KnowledgeNodeType;
    sourceCount: number;
    confidence: number;
    isSearchMatch: boolean;
}

interface GraphEdgeData {
    edge: KnowledgeEdgeRead;
    sourceLabel: string;
}

interface DetailEvidence {
    sources: ResearchSourceRead[];
    claims: string[];
    texts: string[];
}

const NODE_STYLES: Record<KnowledgeNodeType, { border: string; background: string; glow: string }> = {
    Concept: { border: "border-sky-400/30", background: "bg-sky-500/15", glow: "shadow-sky-500/20" },
    Person: { border: "border-violet-400/30", background: "bg-violet-500/15", glow: "shadow-violet-500/20" },
    Organization: { border: "border-emerald-400/30", background: "bg-emerald-500/15", glow: "shadow-emerald-500/20" },
    Technology: { border: "border-cyan-400/30", background: "bg-cyan-500/15", glow: "shadow-cyan-500/20" },
    Paper: { border: "border-fuchsia-400/30", background: "bg-fuchsia-500/15", glow: "shadow-fuchsia-500/20" },
    Method: { border: "border-amber-400/30", background: "bg-amber-500/15", glow: "shadow-amber-500/20" },
    Dataset: { border: "border-orange-400/30", background: "bg-orange-500/15", glow: "shadow-orange-500/20" },
    Benchmark: { border: "border-rose-400/30", background: "bg-rose-500/15", glow: "shadow-rose-500/20" },
};

const EDGE_STYLE: Record<string, string> = {
    supports: "text-emerald-200",
    contradicts: "text-rose-200",
    uses: "text-cyan-200",
    improves: "text-violet-200",
    depends_on: "text-amber-200",
    extends: "text-sky-200",
    cites: "text-fuchsia-200",
};

function normalizeText(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function tokenize(value: string): string[] {
    return normalizeText(value).split(/\s+/).filter((token) => token.length > 2);
}

function classifyNodeType(node: KnowledgeNodeRead): KnowledgeNodeType {
    const text = normalizeText(`${node.concept} ${node.description}`);

    if (/\b(person|researcher|scientist|author|founder|ceo|professor|engineer|analyst|architect)\b/.test(text)) {
        return "Person";
    }
    if (/\b(company|organization|institute|university|lab|foundation|consortium|team|department)\b/.test(text)) {
        return "Organization";
    }
    if (/\b(paper|study|preprint|publication|journal|article|report)\b/.test(text)) {
        return "Paper";
    }
    if (/\b(method|technique|approach|pipeline|procedure|algorithm|workflow|strategy)\b/.test(text)) {
        return "Method";
    }
    if (/\b(dataset|corpus|collection|benchmark dataset|training set)\b/.test(text)) {
        return "Dataset";
    }
    if (/\b(benchmark|leaderboard|eval|evaluation suite|test set)\b/.test(text)) {
        return "Benchmark";
    }
    if (/\b(model|framework|platform|protocol|language|tool|library|api|system|architecture|technology|software)\b/.test(text)) {
        return "Technology";
    }

    return "Concept";
}

function prettifyRelationship(value: string): string {
    return value.replace(/_/g, " ");
}

function getRelationshipLabel(value: string): string {
    if (value === "contrasts_with") return "contradicts";
    return value;
}

function getSourceText(source: ResearchSourceRead): string {
    return normalizeText(
        [
            source.title,
            source.domain,
            source.url,
            source.summary ?? "",
            ...source.key_claims,
            ...source.entities,
            ...source.relationships,
        ].join(" ")
    );
}

function getNodeKeywords(node: KnowledgeNodeRead): string[] {
    return Array.from(new Set([normalizeText(node.concept), ...tokenize(node.concept), ...tokenize(node.description)]))
        .filter((value) => value.length > 2)
        .slice(0, 12);
}

function scoreSourceForNode(source: ResearchSourceRead, keywords: string[]): number {
    const text = getSourceText(source);
    let score = 0;

    for (const keyword of keywords) {
        if (!keyword) continue;
        if (text.includes(keyword)) {
            score += keyword.length >= 10 ? 3 : 1;
        }
    }

    score += source.quality_score >= 0.75 ? 2 : source.quality_score >= 0.5 ? 1 : 0;
    score += source.credibility_score >= 0.75 ? 1 : 0;

    return score;
}

function collectSupportingSources(node: KnowledgeNodeRead, sources: ResearchSourceRead[]): ResearchSourceRead[] {
    const keywords = getNodeKeywords(node);

    return sources
        .map((source) => ({ source, score: scoreSourceForNode(source, keywords) }))
        .filter(({ score }) => score > 0)
        .sort((left, right) => right.score - left.score || right.source.quality_score - left.source.quality_score)
        .map(({ source }) => source)
        .slice(0, 6);
}

function collectSupportingClaims(node: KnowledgeNodeRead, sources: ResearchSourceRead[]): string[] {
    const keywords = getNodeKeywords(node);
    const claims = new Set<string>();

    for (const source of collectSupportingSources(node, sources)) {
        for (const claim of source.key_claims) {
            const text = normalizeText(claim);
            if (keywords.some((keyword) => text.includes(keyword))) {
                claims.add(claim);
            }
        }
    }

    return Array.from(claims).slice(0, 8);
}

function collectNodeTexts(node: KnowledgeNodeRead, sources: ResearchSourceRead[]): string[] {
    const texts = new Set<string>();
    const keywords = getNodeKeywords(node);

    for (const source of collectSupportingSources(node, sources)) {
        for (const text of [source.summary, ...source.relationships].filter(Boolean) as string[]) {
            const normalized = normalizeText(text);
            if (keywords.some((keyword) => normalized.includes(keyword))) {
                texts.add(text);
            }
        }
    }

    return Array.from(texts).slice(0, 8);
}

function collectEdgeEvidence(
    edge: KnowledgeEdgeRead,
    sourceNode: KnowledgeNodeRead | undefined,
    targetNode: KnowledgeNodeRead | undefined,
    sources: ResearchSourceRead[]
): DetailEvidence {
    const keywords = [
        ...(sourceNode ? getNodeKeywords(sourceNode) : []),
        ...(targetNode ? getNodeKeywords(targetNode) : []),
        normalizeText(prettifyRelationship(getRelationshipLabel(edge.relationship))),
    ].filter((keyword) => keyword.length > 2);

    const matchedSources = sources
        .map((source) => {
            const text = getSourceText(source);
            let score = 0;
            for (const keyword of keywords) {
                if (text.includes(keyword)) {
                    score += keyword.length >= 10 ? 2 : 1;
                }
            }
            return { source, score };
        })
        .filter(({ score }) => score > 0)
        .sort((left, right) => right.score - left.score || right.source.quality_score - left.source.quality_score)
        .map(({ source }) => source)
        .slice(0, 6);

    const claims = new Set<string>();
    const texts = new Set<string>();

    for (const source of matchedSources) {
        for (const claim of source.key_claims) {
            const normalized = normalizeText(claim);
            if (keywords.some((keyword) => normalized.includes(keyword))) {
                claims.add(claim);
            }
        }
        for (const relation of source.relationships) {
            const normalized = normalizeText(relation);
            if (keywords.some((keyword) => normalized.includes(keyword))) {
                texts.add(relation);
            }
        }
    }

    return {
        sources: matchedSources,
        claims: Array.from(claims).slice(0, 8),
        texts: Array.from(texts).slice(0, 8),
    };
}

function calculateDegrees(edges: KnowledgeEdgeRead[]): Map<string, number> {
    const degrees = new Map<string, number>();

    for (const edge of edges) {
        degrees.set(edge.source_node, (degrees.get(edge.source_node) ?? 0) + 1);
        degrees.set(edge.target_node, (degrees.get(edge.target_node) ?? 0) + 1);
    }

    return degrees;
}

function layoutNodes(nodes: KnowledgeNodeRead[], degrees: Map<string, number>, searchQuery: string): Node<GraphNodeData>[] {
    const sorted = [...nodes].sort((left, right) => {
        const degreeDiff = (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0);
        if (degreeDiff !== 0) return degreeDiff;
        return right.confidence - left.confidence;
    });

    const query = normalizeText(searchQuery);
    const ringSizes = [1, 6, 10, 14, 18, 22];
    const positions = new Map<string, { x: number; y: number }>();

    let index = 0;
    let ring = 0;

    while (index < sorted.length) {
        const count = ring === 0 ? 1 : ringSizes[Math.min(ring, ringSizes.length - 1)];
        const radius = ring === 0 ? 0 : 220 + ring * 220;

        for (let i = 0; i < count && index < sorted.length; i += 1, index += 1) {
            if (ring === 0) {
                positions.set(sorted[index].id, { x: 0, y: 0 });
                continue;
            }

            const angle = ((Math.PI * 2) / count) * i + ring * 0.35;
            positions.set(sorted[index].id, {
                x: Math.cos(angle) * radius,
                y: Math.sin(angle) * radius,
            });
        }

        ring += 1;
    }

    return sorted.map((node) => {
        const position = positions.get(node.id) ?? { x: 0, y: 0 };
        const nodeType = classifyNodeType(node);
        const isSearchMatch =
            !query ||
            normalizeText(node.concept).includes(query) ||
            normalizeText(node.description).includes(query);

        return {
            id: node.id,
            type: "knowledgeNode",
            position: {
                x: position.x - NODE_WIDTH / 2,
                y: position.y - NODE_HEIGHT / 2,
            },
            data: {
                node,
                nodeType,
                sourceCount: node.source_count,
                confidence: node.confidence,
                isSearchMatch,
            },
            style: {
                width: NODE_WIDTH,
                opacity: isSearchMatch ? 1 : query ? 0.22 : 1,
                zIndex: isSearchMatch ? 20 : 1,
            },
        };
    });
}

function buildEdges(edges: KnowledgeEdgeRead[]): Edge<GraphEdgeData>[] {
    return edges.map((edge) => {
        const label = prettifyRelationship(getRelationshipLabel(edge.relationship));
        return {
            id: edge.id,
            source: edge.source_node,
            target: edge.target_node,
            type: "smoothstep",
            animated: true,
            label,
            labelStyle: {
                fill: "#e5e7eb",
                fontSize: 11,
                fontWeight: 600,
            },
            style: {
                strokeWidth: 2,
                stroke: "rgba(148, 163, 184, 0.8)",
            },
            markerEnd: {
                type: MarkerType.ArrowClosed,
                width: 18,
                height: 18,
                color: "rgba(148, 163, 184, 0.8)",
            },
            data: {
                edge,
                sourceLabel: label,
            },
        };
    });
}

function KnowledgeNodeView({ data }: NodeProps<GraphNodeData>) {
    const style = NODE_STYLES[data.nodeType];

    return (
        <div
            className={cn(
                "rounded-2xl border bg-slate-950/85 px-4 py-3 text-white shadow-2xl backdrop-blur-md",
                style.border,
                style.background,
                style.glow,
                data.isSearchMatch ? "ring-1 ring-white/20" : ""
            )}
        >
            <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-white/70" />
            <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-white/70" />

            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{data.node.concept}</div>
                    <div className="mt-1 text-[11px] uppercase tracking-[0.22em] text-white/55">{data.nodeType}</div>
                </div>
                <div className="rounded-full border border-white/10 bg-black/25 px-2 py-1 text-[11px] text-white/75">
                    {Math.round(data.confidence * 100)}%
                </div>
            </div>

            <div className="mt-3 line-clamp-2 text-xs leading-5 text-white/68">{data.node.description}</div>

            <div className="mt-3 flex items-center justify-between text-[11px] text-white/50">
                <span>{data.sourceCount} sources</span>
                <span>Node</span>
            </div>
        </div>
    );
}

function MetricCard({ label, value, subtitle }: { label: string; value: string; subtitle?: string }) {
    return (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-md">
            <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{label}</div>
            <div className="mt-2 text-lg font-semibold text-white">{value}</div>
            {subtitle ? <div className="mt-1 text-xs text-white/50">{subtitle}</div> : null}
        </div>
    );
}

function PillList({ items }: { items: string[] }) {
    return (
        <div className="flex flex-wrap gap-2">
            {items.length ? items.map((item) => (
                <span key={item} className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-white/70">
                    {item}
                </span>
            )) : <span className="text-sm text-white/55">None</span>}
        </div>
    );
}

function GraphCanvas({
    nodes,
    edges,
    onSelectNode,
    onSelectEdge,
    focusNodeId,
}: {
    nodes: Node<GraphNodeData>[];
    edges: Edge<GraphEdgeData>[];
    onSelectNode: (nodeId: string) => void;
    onSelectEdge: (edgeId: string) => void;
    focusNodeId: string | null;
}) {
    const { fitView, setCenter, getNode } = useReactFlow();

    useEffect(() => {
        if (nodes.length > 0) {
            fitView({ padding: 0.22, duration: 450 });
        }
    }, [nodes, fitView]);

    useEffect(() => {
        if (!focusNodeId) return;
        const node = getNode(focusNodeId);
        if (!node) return;

        setCenter(node.position.x + NODE_WIDTH / 2, node.position.y + NODE_HEIGHT / 2, {
            zoom: 1.2,
            duration: 350,
        });
    }, [focusNodeId, getNode, setCenter]);

    return (
        <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={{ knowledgeNode: KnowledgeNodeView }}
            onNodeClick={(_, node) => onSelectNode(node.id)}
            onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
            onPaneClick={() => onSelectNode("")}
            fitView
            minZoom={0.25}
            maxZoom={2.5}
            defaultEdgeOptions={{ animated: true }}
            proOptions={{ hideAttribution: true }}
        >
            <Background color="rgba(148, 163, 184, 0.18)" gap={24} />
            <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
    );
}

export function KnowledgeGraphWorkspace({ sessionId, knowledge, sources }: KnowledgeGraphWorkspaceProps) {
    const [search, setSearch] = useState("");
    const [selection, setSelection] = useState<Selection>(null);
    const [focusNodeId, setFocusNodeId] = useState<string | null>(null);

    const degrees = useMemo(() => calculateDegrees(knowledge.edges), [knowledge.edges]);
    const graphNodes = useMemo(() => layoutNodes(knowledge.nodes, degrees, search), [knowledge.nodes, degrees, search]);
    const graphEdges = useMemo(() => buildEdges(knowledge.edges), [knowledge.edges]);

    const nodeMap = useMemo(() => new Map(knowledge.nodes.map((node) => [node.id, node])), [knowledge.nodes]);
    const edgeMap = useMemo(() => new Map(knowledge.edges.map((edge) => [edge.id, edge])), [knowledge.edges]);

    const selectedNode = selection?.kind === "node" ? nodeMap.get(selection.id) ?? null : null;
    const selectedEdge = selection?.kind === "edge" ? edgeMap.get(selection.id) ?? null : null;

    const selectedNodeInspector = useMemo(() => {
        if (!selectedNode) return null;

        const connectedNodeIds = knowledge.edges
            .filter((edge) => edge.source_node === selectedNode.id || edge.target_node === selectedNode.id)
            .map((edge) => (edge.source_node === selectedNode.id ? edge.target_node : edge.source_node));

        const connectedNodes = connectedNodeIds
            .map((id) => nodeMap.get(id))
            .filter((node): node is KnowledgeNodeRead => Boolean(node));

        const supportingSources = collectSupportingSources(selectedNode, sources);
        const supportingClaims = collectSupportingClaims(selectedNode, sources);
        const evidenceTexts = collectNodeTexts(selectedNode, sources);

        return {
            nodeType: classifyNodeType(selectedNode),
            connectedNodes,
            supportingSources,
            supportingClaims,
            evidenceTexts,
        };
    }, [selectedNode, knowledge.edges, nodeMap, sources]);

    const selectedEdgeInspector = useMemo(() => {
        if (!selectedEdge) return null;

        const sourceNode = nodeMap.get(selectedEdge.source_node);
        const targetNode = nodeMap.get(selectedEdge.target_node);
        const evidence = collectEdgeEvidence(selectedEdge, sourceNode, targetNode, sources);

        return {
            sourceNode,
            targetNode,
            evidence,
        };
    }, [selectedEdge, nodeMap, sources]);

    const searchMatches = useMemo(() => {
        const query = normalizeText(search);
        if (!query) return [] as KnowledgeNodeRead[];

        return knowledge.nodes.filter((node) => {
            const haystack = normalizeText(`${node.concept} ${node.description}`);
            return haystack.includes(query);
        });
    }, [knowledge.nodes, search]);

    const metrics = useMemo(() => {
        const topConcepts = [...knowledge.nodes].sort((left, right) => right.source_count - left.source_count).slice(0, 5);
        const mostConnected = [...knowledge.nodes]
            .sort((left, right) => (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0) || right.confidence - left.confidence)
            .slice(0, 5);
        const highestConfidence = [...knowledge.nodes].sort((left, right) => right.confidence - left.confidence).slice(0, 5);
        const contradictions = knowledge.edges.filter((edge) => normalizeText(edge.relationship).includes("contradict") || edge.relationship === "contrasts_with");
        const orphanNodes = knowledge.nodes.filter((node) => (degrees.get(node.id) ?? 0) === 0).slice(0, 5);

        return {
            topConcepts,
            mostConnected,
            highestConfidence,
            contradictions,
            orphanNodes,
        };
    }, [degrees, knowledge.edges, knowledge.nodes]);

    const handleSearch = () => {
        if (searchMatches.length > 0) {
            setSelection({ kind: "node", id: searchMatches[0].id });
            setFocusNodeId(searchMatches[0].id);
        }
    };

    return (
        <ReactFlowProvider>
            <div className="space-y-6 text-white">
                <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-5">
                    <MetricCard label="Top Concepts" value={String(metrics.topConcepts.length)} subtitle={metrics.topConcepts[0]?.concept ?? "No nodes"} />
                    <MetricCard label="Most Connected" value={String(metrics.mostConnected.length)} subtitle={metrics.mostConnected[0]?.concept ?? "No nodes"} />
                    <MetricCard label="Highest Confidence" value={String(metrics.highestConfidence.length)} subtitle={metrics.highestConfidence[0]?.concept ?? "No nodes"} />
                    <MetricCard label="Contradictions" value={String(metrics.contradictions.length)} subtitle={metrics.contradictions[0] ? prettifyRelationship(getRelationshipLabel(metrics.contradictions[0].relationship)) : "None"} />
                    <MetricCard label="Orphan Nodes" value={String(metrics.orphanNodes.length)} subtitle={metrics.orphanNodes[0]?.concept ?? "None"} />
                </div>

                <div className="grid gap-6 xl:grid-cols-[minmax(0,1.7fr)_minmax(380px,0.9fr)]">
                    <div className="overflow-hidden rounded-3xl border border-white/10 bg-slate-950/70 shadow-2xl shadow-black/30 backdrop-blur-xl">
                        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-4">
                            <div>
                                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.28em] text-white/45">
                                    <CircleDot className="h-4 w-4" /> Knowledge Graph
                                </div>
                                <div className="mt-1 text-sm text-white/55">Session {sessionId}</div>
                            </div>

                            <div className="flex flex-1 flex-wrap items-center justify-end gap-2 lg:flex-none">
                                <div className="flex min-w-[240px] items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/75">
                                    <Search className="h-4 w-4 text-white/40" />
                                    <input
                                        value={search}
                                        onChange={(event) => setSearch(event.target.value)}
                                        onKeyDown={(event) => {
                                            if (event.key === "Enter") {
                                                event.preventDefault();
                                                handleSearch();
                                            }
                                        }}
                                        placeholder="Search nodes"
                                        className="w-full bg-transparent outline-none placeholder:text-white/35"
                                    />
                                </div>
                                <button
                                    type="button"
                                    onClick={handleSearch}
                                    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white/80 transition hover:border-white/20 hover:bg-white/10"
                                >
                                    <ZoomIn className="h-4 w-4" /> Find
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setFocusNodeId(selectedNode?.id ?? searchMatches[0]?.id ?? null)}
                                    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white/80 transition hover:border-white/20 hover:bg-white/10"
                                >
                                    <Maximize2 className="h-4 w-4" /> Fit View
                                </button>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setSearch("");
                                        setSelection(null);
                                        setFocusNodeId(null);
                                    }}
                                    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white/80 transition hover:border-white/20 hover:bg-white/10"
                                >
                                    <RotateCcw className="h-4 w-4" /> Clear
                                </button>
                            </div>
                        </div>

                        <div className="h-[78vh] min-h-[680px] w-full">
                            {knowledge.nodes.length || knowledge.edges.length ? (
                                <GraphCanvas
                                    nodes={graphNodes}
                                    edges={graphEdges}
                                    onSelectNode={(nodeId) => setSelection(nodeId ? { kind: "node", id: nodeId } : null)}
                                    onSelectEdge={(edgeId) => setSelection({ kind: "edge", id: edgeId })}
                                    focusNodeId={focusNodeId}
                                />
                            ) : (
                                <div className="flex h-full items-center justify-center p-10 text-center text-white/55">
                                    No knowledge graph has been built for this session yet.
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl">
                            <div className="text-xs uppercase tracking-[0.28em] text-white/45">Node Inspector</div>
                            {selectedNode && selectedNodeInspector ? (
                                <div className="mt-4 space-y-5">
                                    <div>
                                        <div className="text-2xl font-semibold text-white">{selectedNode.concept}</div>
                                        <div className="mt-1 text-sm text-white/55">{selectedNodeInspector.nodeType}</div>
                                        <div className="mt-3 rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-white/70">
                                            {selectedNode.description}
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-3">
                                        <MetricCard label="Confidence" value={`${Math.round(selectedNode.confidence * 100)}%`} />
                                        <MetricCard label="Source Count" value={String(selectedNode.source_count)} />
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Connected Nodes</div>
                                        <PillList items={selectedNodeInspector.connectedNodes.map((node) => node.concept)} />
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Supporting Sources</div>
                                        <div className="space-y-2">
                                            {selectedNodeInspector.supportingSources.length ? selectedNodeInspector.supportingSources.map((source) => (
                                                <div key={source.page_id} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/75">
                                                    <div className="font-medium text-white">{source.title}</div>
                                                    <div className="mt-1 text-xs text-white/45">{source.domain} · {source.research_relevance}</div>
                                                </div>
                                            )) : <div className="text-sm text-white/55">No direct source evidence found.</div>}
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Supporting Claims</div>
                                        <div className="space-y-2">
                                            {selectedNodeInspector.supportingClaims.length ? selectedNodeInspector.supportingClaims.map((claim) => (
                                                <div key={claim} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/70">
                                                    {claim}
                                                </div>
                                            )) : <div className="text-sm text-white/55">No supporting claims matched this node yet.</div>}
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Evidence Text</div>
                                        <div className="space-y-2">
                                            {selectedNodeInspector.evidenceTexts.length ? selectedNodeInspector.evidenceTexts.map((text) => (
                                                <div key={text} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/65">
                                                    {text}
                                                </div>
                                            )) : <div className="text-sm text-white/55">No structured evidence text matched this node.</div>}
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="mt-4 text-sm text-white/55">
                                    Click a node to inspect its confidence, connected nodes, sources, and claims.
                                </div>
                            )}
                        </div>

                        <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl">
                            <div className="text-xs uppercase tracking-[0.28em] text-white/45">Edge Inspector</div>
                            {selectedEdge && selectedEdgeInspector ? (
                                <div className="mt-4 space-y-5">
                                    <div>
                                        <div className="text-lg font-semibold text-white">
                                            {(selectedEdgeInspector.sourceNode?.concept ?? selectedEdge.source_node)}
                                        </div>
                                        <div className={cn("mt-1 text-sm font-medium", EDGE_STYLE[selectedEdge.relationship] ?? "text-white/70")}>
                                            {prettifyRelationship(getRelationshipLabel(selectedEdge.relationship))}
                                        </div>
                                        <div className="mt-1 text-lg font-semibold text-white">
                                            {(selectedEdgeInspector.targetNode?.concept ?? selectedEdge.target_node)}
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Evidence</div>
                                        <div className="space-y-2">
                                            {selectedEdgeInspector.evidence.texts.length ? selectedEdgeInspector.evidence.texts.map((text) => (
                                                <div key={text} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/70">
                                                    {text}
                                                </div>
                                            )) : <div className="text-sm text-white/55">No edge evidence text found.</div>}
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Supporting Sources</div>
                                        <div className="space-y-2">
                                            {selectedEdgeInspector.evidence.sources.length ? selectedEdgeInspector.evidence.sources.map((source) => (
                                                <div key={source.page_id} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/75">
                                                    <div className="font-medium text-white">{source.title}</div>
                                                    <div className="mt-1 text-xs text-white/45">{source.domain} · {source.research_relevance}</div>
                                                </div>
                                            )) : <div className="text-sm text-white/55">No supporting sources matched this edge yet.</div>}
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <div className="text-sm font-semibold text-white">Supporting Claims</div>
                                        <div className="space-y-2">
                                            {selectedEdgeInspector.evidence.claims.length ? selectedEdgeInspector.evidence.claims.map((claim) => (
                                                <div key={claim} className="rounded-2xl border border-white/10 bg-black/15 p-3 text-sm text-white/70">
                                                    {claim}
                                                </div>
                                            )) : <div className="text-sm text-white/55">No supporting claims matched this edge yet.</div>}
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="mt-4 text-sm text-white/55">
                                    Click an edge to inspect its relationship, evidence, sources, and claims.
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {search && searchMatches.length > 0 ? (
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/65">
                        Showing {searchMatches.length} matching node{searchMatches.length === 1 ? "" : "s"} for “{search}”.
                    </div>
                ) : null}
            </div>
        </ReactFlowProvider>
    );
}

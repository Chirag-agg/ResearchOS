"use client";

import { useState } from "react";
import type { ResearchSourceRead } from "@/types/workspace";

interface SourceDetailsProps {
    source: ResearchSourceRead;
}

function DetailCard({ title, children }: { title: string; children: React.ReactNode }) {
    const [open, setOpen] = useState(true);

    return (
        <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-md">
            <button
                type="button"
                onClick={() => setOpen((current) => !current)}
                className="flex w-full items-center justify-between px-4 py-3 text-left"
            >
                <span className="text-sm font-semibold text-white">{title}</span>
                <span className="text-white/40">{open ? "−" : "+"}</span>
            </button>
            {open && <div className="border-t border-white/10 px-4 py-4 text-sm text-white/75">{children}</div>}
        </div>
    );
}

export function SourceDetails({ source }: SourceDetailsProps) {
    return (
        <div className="space-y-4">
            <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-md">
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <div className="text-xs uppercase tracking-[0.25em] text-white/45">Source Details</div>
                        <h3 className="mt-2 text-xl font-semibold text-white">{source.title}</h3>
                        <p className="mt-1 break-all text-sm text-primary">{source.url}</p>
                    </div>
                    <div className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-white/70">
                        {source.domain}
                    </div>
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Stat label="Type" value={source.source_type} />
                    <Stat label="Credibility" value={`${Math.round(source.credibility_score * 100)}%`} />
                    <Stat label="Fetch" value={source.fetch_duration_ms ? `${Math.round(source.fetch_duration_ms)} ms` : "n/a"} />
                    <Stat label="Analysis" value={source.analysis_duration_ms ? `${Math.round(source.analysis_duration_ms)} ms` : "n/a"} />
                    <Stat label="Word Count" value={source.word_count} />
                    <Stat label="Token Count" value={source.token_count} />
                    <Stat label="Quality" value={source.extraction_quality_score.toFixed(2)} />
                    <Stat label="Relevance" value={source.research_relevance} />
                </div>
            </div>

            <div className="space-y-3">
                <DetailCard title="Raw Summary">{source.summary || "No structured summary was extracted for this source."}</DetailCard>
                <DetailCard title="Key Claims">
                    {source.key_claims.length > 0 ? (
                        <ul className="space-y-2">
                            {source.key_claims.map((claim) => (
                                <li key={claim} className="rounded-lg border border-white/10 bg-black/10 px-3 py-2">
                                    {claim}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        "No claims were extracted for this source."
                    )}
                </DetailCard>
                <DetailCard title="Entities Found">
                    {source.entities.length > 0 ? source.entities.join(", ") : "No named entities were extracted."}
                </DetailCard>
                <DetailCard title="Relationships Found">
                    {source.relationships.length > 0 ? source.relationships.join(" • ") : "No graph relationships were linked to this source yet."}
                </DetailCard>
                <DetailCard title="Research Relevance">{source.research_relevance}</DetailCard>
            </div>
        </div>
    );
}

function Stat({ label, value }: { label: string; value: string | number }) {
    return (
        <div className="rounded-xl border border-white/10 bg-black/10 px-3 py-3">
            <div className="text-[11px] uppercase tracking-[0.2em] text-white/40">{label}</div>
            <div className="mt-1 text-sm font-medium text-white">{value}</div>
        </div>
    );
}
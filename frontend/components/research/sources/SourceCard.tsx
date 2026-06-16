"use client";

import { cn } from "@/lib/utils";
import type { ResearchSourceRead } from "@/types/workspace";

interface SourceCardProps {
    source: ResearchSourceRead;
    selected?: boolean;
    onClick: () => void;
}

function getGrade(source: ResearchSourceRead): string {
    if (source.domain.includes("arxiv.org") || source.domain.includes("nature.com") || source.domain.includes("acm.org")) return "A";
    if (source.domain.includes("wikipedia.org")) return "B";
    if (source.source_type === "documentation") return "A";
    if (source.source_type === "news") return "B";
    if (source.source_type === "blogs") return "D";
    return source.credibility_score >= 0.85 ? "A" : source.credibility_score >= 0.7 ? "B" : source.credibility_score >= 0.5 ? "C" : "E";
}

function gradeStyle(grade: string): string {
    if (grade === "A") return "bg-emerald-500/15 text-emerald-200 border-emerald-500/30";
    if (grade === "B") return "bg-sky-500/15 text-sky-200 border-sky-500/30";
    if (grade === "C") return "bg-amber-500/15 text-amber-200 border-amber-500/30";
    if (grade === "D") return "bg-orange-500/15 text-orange-200 border-orange-500/30";
    return "bg-red-500/15 text-red-200 border-red-500/30";
}

export function SourceCard({ source, selected = false, onClick }: SourceCardProps) {
    const grade = getGrade(source);
    const isAnalyzed = source.analysis_status === "analyzed";

    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                "w-full rounded-2xl border p-4 text-left transition-all",
                "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10",
                selected && "border-primary/60 bg-primary/10 ring-1 ring-primary/30"
            )}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 gap-3">
                    <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black/20">
                        <img
                            src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(source.domain)}&sz=64`}
                            alt=""
                            className="h-5 w-5"
                            loading="lazy"
                        />
                    </div>
                    <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-white">{source.title}</div>
                        <div className="truncate text-xs text-white/45">{source.domain}</div>
                    </div>
                </div>
                <span className={cn("rounded-full border px-2 py-1 text-[11px] font-semibold", gradeStyle(grade))}>
                    {grade}
                </span>
            </div>

            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-white/60">
                <span className="rounded-full border border-white/10 px-2 py-1">{source.source_type}</span>
                <span className="rounded-full border border-white/10 px-2 py-1">{source.status}</span>
                <span className={cn("rounded-full border px-2 py-1", isAnalyzed ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-100" : "border-amber-500/20 bg-amber-500/10 text-amber-100")}>
                    {source.analysis_status}
                </span>
                <span className="rounded-full border border-white/10 px-2 py-1">Quality {source.quality_score.toFixed(2)}</span>
            </div>

            <div className="mt-3 flex items-center justify-between text-xs text-white/45">
                <span>{source.research_relevance}</span>
                <span>{source.analysis_duration_ms ? `${Math.round(source.analysis_duration_ms)} ms` : "n/a"}</span>
            </div>
        </button>
    );
}
"use client";

import { cn } from "@/lib/utils";

export type SourceFilterId =
    | "all"
    | "academic"
    | "documentation"
    | "news"
    | "blogs"
    | "low"
    | "high";

interface SourceFiltersProps {
    value: SourceFilterId;
    onChange: (value: SourceFilterId) => void;
}

const FILTERS: { id: SourceFilterId; label: string }[] = [
    { id: "all", label: "All" },
    { id: "academic", label: "Academic" },
    { id: "documentation", label: "Documentation" },
    { id: "news", label: "News" },
    { id: "blogs", label: "Blogs" },
    { id: "low", label: "Low Quality" },
    { id: "high", label: "High Quality" },
];

export function SourceFilters({ value, onChange }: SourceFiltersProps) {
    return (
        <div className="flex flex-wrap gap-2">
            {FILTERS.map((filter) => {
                const active = value === filter.id;
                return (
                    <button
                        key={filter.id}
                        type="button"
                        onClick={() => onChange(filter.id)}
                        className={cn(
                            "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                            active
                                ? "border-primary/60 bg-primary/15 text-white"
                                : "border-white/10 bg-white/5 text-white/70 hover:border-white/20 hover:bg-white/10"
                        )}
                    >
                        {filter.label}
                    </button>
                );
            })}
        </div>
    );
}
"use client";

import type { ResearchSourceRead } from "@/types/workspace";
import { SourceCard } from "./SourceCard";

interface SourceListProps {
    sources: ResearchSourceRead[];
    selectedSourceId?: string | null;
    onSelectSource: (sourceId: string) => void;
}

export function SourceList({ sources, selectedSourceId, onSelectSource }: SourceListProps) {
    return (
        <div className="flex flex-col gap-3">
            {sources.map((source) => (
                <SourceCard
                    key={source.page_id}
                    source={source}
                    selected={selectedSourceId === source.page_id}
                    onClick={() => onSelectSource(source.page_id)}
                />
            ))}
        </div>
    );
}
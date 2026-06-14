"use client";

import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { SUGGESTED_TOPICS } from "@/types/research";

interface SuggestedChipsProps {
  onSelect: (topic: string) => void;
  disabled?: boolean;
}

export function SuggestedChips({
  onSelect,
  disabled = false,
}: SuggestedChipsProps) {
  return (
    <div className="space-y-3">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Suggested topics
      </p>
      <div className="flex flex-wrap gap-2">
        {SUGGESTED_TOPICS.map((topic) => (
          <button
            key={topic}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(topic)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-foreground/90 backdrop-blur-md transition-all",
              "hover:border-primary/40 hover:bg-primary/10 hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50"
            )}
          >
            <Sparkles className="h-3.5 w-3.5 text-primary/80" />
            {topic}
          </button>
        ))}
      </div>
    </div>
  );
}

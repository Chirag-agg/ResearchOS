"use client";

import { cn } from "@/lib/utils";
import { RESEARCH_MODES, type ResearchMode } from "@/types/research";

interface ResearchModesProps {
  value: ResearchMode;
  onChange: (mode: ResearchMode) => void;
  disabled?: boolean;
}

export function ResearchModes({
  value,
  onChange,
  disabled = false,
}: ResearchModesProps) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {RESEARCH_MODES.map((mode) => {
        const isSelected = value === mode.id;

        return (
          <button
            key={mode.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(mode.id)}
            className={cn(
              "group relative rounded-xl border p-4 text-left transition-all",
              "border-white/10 bg-white/5 backdrop-blur-md",
              "hover:border-white/20 hover:bg-white/10",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isSelected &&
                "border-primary/60 bg-primary/15 shadow-lg shadow-primary/10 ring-1 ring-primary/40"
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className={cn(
                  "text-sm font-semibold",
                  isSelected ? "text-primary-foreground" : "text-foreground"
                )}
              >
                {mode.label}
              </span>
              {isSelected && (
                <span className="h-2 w-2 rounded-full bg-primary shadow-[0_0_8px_rgba(139,92,246,0.8)]" />
              )}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Estimated: {mode.estimatedTime}
            </p>
          </button>
        );
      })}
    </div>
  );
}

"use client";

import { ChevronDown, Settings2 } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

interface AdvancedOptionsProps {
  maxRounds: number;
  confidenceThreshold: number;
  onMaxRoundsChange: (value: number) => void;
  onConfidenceThresholdChange: (value: number) => void;
  disabled?: boolean;
}

export function AdvancedOptions({
  maxRounds,
  confidenceThreshold,
  onMaxRoundsChange,
  onConfidenceThresholdChange,
  disabled = false,
}: AdvancedOptionsProps) {
  return (
    <Collapsible>
      <CollapsibleTrigger
        disabled={disabled}
        className={cn(
          "flex w-full items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium backdrop-blur-md transition-all",
          "hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "group data-[state=open]:rounded-b-none data-[state=open]:border-b-0"
        )}
      >
        <span className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-muted-foreground" />
          Advanced Options
        </span>
        <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>

      <CollapsibleContent className="rounded-b-xl border border-t-0 border-white/10 bg-white/5 px-4 py-5 backdrop-blur-md">
        <div className="space-y-6">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-foreground">
                Maximum Research Rounds
              </label>
              <span className="rounded-md bg-white/10 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {maxRounds}
              </span>
            </div>
            <Slider
              value={[maxRounds]}
              onValueChange={(values) => onMaxRoundsChange(values[0] ?? 3)}
              min={1}
              max={5}
              step={1}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Controls how many iterative research rounds to run (1–5).
            </p>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-foreground">
                Confidence Threshold
              </label>
              <span className="rounded-md bg-white/10 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {confidenceThreshold.toFixed(2)}
              </span>
            </div>
            <Slider
              value={[confidenceThreshold]}
              onValueChange={(values) =>
                onConfidenceThresholdChange(values[0] ?? 0.8)
              }
              min={0.5}
              max={1.0}
              step={0.05}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Research stops when confidence reaches this threshold (0.50–1.00).
            </p>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

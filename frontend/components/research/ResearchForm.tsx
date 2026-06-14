"use client";

import { useCallback, useMemo, useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResearchInput } from "@/components/research/ResearchInput";
import { ResearchModes } from "@/components/research/ResearchModes";
import { AdvancedOptions } from "@/components/research/AdvancedOptions";
import { SuggestedChips } from "@/components/research/SuggestedChips";
import { useCreateResearch } from "@/hooks/useCreateResearch";
import {
  DEFAULT_RESEARCH_MODE,
  RESEARCH_MODES,
  type ResearchMode,
} from "@/types/research";

function getModeDefaults(mode: ResearchMode) {
  const config = RESEARCH_MODES.find((item) => item.id === mode);
  return {
    maxRounds: config?.maxRounds ?? 3,
    confidenceThreshold: config?.confidenceThreshold ?? 0.8,
  };
}

export function ResearchForm() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<ResearchMode>(DEFAULT_RESEARCH_MODE);
  const [maxRounds, setMaxRounds] = useState(
    () => getModeDefaults(DEFAULT_RESEARCH_MODE).maxRounds
  );
  const [confidenceThreshold, setConfidenceThreshold] = useState(
    () => getModeDefaults(DEFAULT_RESEARCH_MODE).confidenceThreshold
  );

  const { mutate, isPending } = useCreateResearch();

  const isQuestionEmpty = useMemo(() => question.trim().length === 0, [question]);
  const isDisabled = isPending;

  const handleModeChange = useCallback((nextMode: ResearchMode) => {
    setMode(nextMode);
    const defaults = getModeDefaults(nextMode);
    setMaxRounds(defaults.maxRounds);
    setConfidenceThreshold(defaults.confidenceThreshold);
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || isPending) return;

    mutate({
      question: trimmedQuestion,
      max_rounds: maxRounds,
      confidence_threshold: confidenceThreshold,
    });
  }, [question, isPending, maxRounds, confidenceThreshold, mutate]);

  return (
    <div className="space-y-6">
      <ResearchInput
        value={question}
        onChange={setQuestion}
        disabled={isDisabled}
      />

      <ResearchModes
        value={mode}
        onChange={handleModeChange}
        disabled={isDisabled}
      />

      <AdvancedOptions
        maxRounds={maxRounds}
        confidenceThreshold={confidenceThreshold}
        onMaxRoundsChange={setMaxRounds}
        onConfidenceThresholdChange={setConfidenceThreshold}
        disabled={isDisabled}
      />

      <SuggestedChips onSelect={setQuestion} disabled={isDisabled} />

      <Button
        type="button"
        size="xl"
        className="w-full"
        disabled={isQuestionEmpty || isDisabled}
        onClick={handleSubmit}
      >
        {isPending ? (
          <>
            <Loader2 className="h-5 w-5 animate-spin" />
            Creating research session...
          </>
        ) : (
          <>
            <Brain className="h-5 w-5" />
            Research
          </>
        )}
      </Button>
    </div>
  );
}

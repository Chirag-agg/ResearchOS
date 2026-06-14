"use client";

import { useCallback, useEffect, useRef } from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface ResearchInputProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function ResearchInput({
  value,
  onChange,
  disabled = false,
}: ResearchInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    const nextHeight = Math.max(textarea.scrollHeight, 180);
    textarea.style.height = `${nextHeight}px`;
  }, []);

  useEffect(() => {
    resizeTextarea();
  }, [value, resizeTextarea]);

  return (
    <div className="relative">
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onInput={resizeTextarea}
        placeholder="What topic are you curious about?"
        disabled={disabled}
        className="min-h-[180px] resize-none pb-10 text-base leading-relaxed"
      />
      <div
        className={cn(
          "pointer-events-none absolute bottom-3 right-4 text-xs text-muted-foreground",
          disabled && "opacity-50"
        )}
      >
        {value.length} characters
      </div>
    </div>
  );
}

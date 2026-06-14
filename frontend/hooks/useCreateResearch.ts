"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ApiError, createResearch } from "@/lib/api";
import { toast } from "@/hooks/use-toast";
import type { CreateResearchRequest } from "@/types/research";

function getErrorToastContent(error: unknown): {
  title: string;
  description: string;
} {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "offline":
        return {
          title: "Backend offline",
          description: error.message,
        };
      case "timeout":
        return {
          title: "Request timed out",
          description: error.message,
        };
      case "invalid_response":
        return {
          title: "Invalid response",
          description: error.message,
        };
      default:
        return {
          title: "Research failed",
          description: error.message,
        };
    }
  }

  return {
    title: "Unknown error",
    description:
      "Something went wrong while creating your research session. Please try again.",
  };
}

export function useCreateResearch() {
  const router = useRouter();

  return useMutation({
    mutationFn: (payload: CreateResearchRequest) => createResearch(payload),
    onSuccess: (data) => {
      router.push(`/research/${data.session_id}`);
    },
    onError: (error) => {
      const content = getErrorToastContent(error);
      toast({
        variant: "destructive",
        title: content.title,
        description: content.description,
      });
    },
  });
}

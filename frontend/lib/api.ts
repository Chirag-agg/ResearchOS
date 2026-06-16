import type {
  CreateResearchRequest,
  CreateResearchResponse,
  LiveResearchStatus,
  TelemetryEventRead,
  ResearchMetrics,
} from "@/types/research";
import type {
  KnowledgeGraphResponse,
  ResearchSourcesResponse,
} from "@/types/workspace";
import type { ReasoningResponse } from "@/types/reasoning";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: "offline" | "timeout" | "invalid_response" | "unknown"
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getApiBaseUrl(): string {
  return API_URL.replace(/\/$/, "");
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError(
      "Received an invalid response from the server.",
      response.status,
      "invalid_response"
    );
  }
}

function extractErrorMessage(data: unknown, fallback: string): string {
  if (
    data &&
    typeof data === "object" &&
    "detail" in data &&
    typeof data.detail === "string"
  ) {
    return data.detail;
  }

  return fallback;
}

export async function createResearch(
  payload: CreateResearchRequest
): Promise<CreateResearchResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/v1/research/run-iterative/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      }
    );

    const data = await parseJsonResponse(response);

    if (!response.ok) {
      throw new ApiError(
        extractErrorMessage(
          data,
          `Research request failed with status ${response.status}.`
        ),
        response.status,
        "unknown"
      );
    }

    if (
      !data ||
      typeof data !== "object" ||
      !("session_id" in data) ||
      typeof data.session_id !== "string" ||
      !("status" in data) ||
      typeof data.status !== "string"
    ) {
      throw new ApiError(
        "The server returned an unexpected response format.",
        response.status,
        "invalid_response"
      );
    }

    return data as CreateResearchResponse;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The research request timed out. Please try again.",
        undefined,
        "timeout"
      );
    }

    if (error instanceof TypeError) {
      throw new ApiError(
        "Unable to reach the backend. Make sure the API server is running.",
        undefined,
        "offline"
      );
    }

    throw new ApiError(
      "An unexpected error occurred while creating the research session.",
      undefined,
      "unknown"
    );
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function getResearchLiveStatus(
  sessionId: string
): Promise<LiveResearchStatus> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/live`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch live status (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as LiveResearchStatus;
}

export async function getResearchTimeline(
  sessionId: string
): Promise<TelemetryEventRead[]> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/timeline`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch timeline (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as TelemetryEventRead[];
}

export async function getResearchMetrics(
  sessionId: string
): Promise<ResearchMetrics> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/metrics`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch metrics (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as ResearchMetrics;
}

export async function getResearchSources(
  sessionId: string
): Promise<ResearchSourcesResponse> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/sources`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch sources (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as ResearchSourcesResponse;
}

export async function getResearchKnowledge(
  sessionId: string
): Promise<KnowledgeGraphResponse> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/knowledge`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch knowledge graph (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as KnowledgeGraphResponse;
}

export async function getResearchReasoning(
  sessionId: string
): Promise<ReasoningResponse> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/research/${sessionId}/reasoning`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const data = await parseJsonResponse(response).catch(() => null);
    throw new ApiError(
      extractErrorMessage(data, `Failed to fetch reasoning trail (${response.status})`),
      response.status
    );
  }

  return (await parseJsonResponse(response)) as ReasoningResponse;
}

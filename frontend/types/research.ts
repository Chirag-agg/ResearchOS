export type ResearchMode = "quick" | "deep" | "technical";

export interface ResearchModeConfig {
  id: ResearchMode;
  label: string;
  estimatedTime: string;
  maxRounds: number;
  confidenceThreshold: number;
}

export interface CreateResearchRequest {
  question: string;
  max_rounds: number;
  confidence_threshold: number;
}

export interface IterativeResearchRoundMetrics {
  round_number: number;
  queries_generated: number;
  results_found: number;
  pages_fetched: number;
  concepts_added: number;
  coverage_score: number;
  confidence_score: number;
  knowledge_growth: number;
}

export interface CreateResearchResponse {
  session_id: string;
  question: string;
  rounds_executed: number;
  final_coverage_score: number;
  final_confidence_score: number;
  total_concepts: number;
  stopped_reason: string;
  round_metrics: IterativeResearchRoundMetrics[];
}

export interface ResearchFormState {
  question: string;
  mode: ResearchMode;
  maxRounds: number;
  confidenceThreshold: number;
}

export const RESEARCH_MODES: ResearchModeConfig[] = [
  {
    id: "quick",
    label: "Quick",
    estimatedTime: "30 seconds",
    maxRounds: 1,
    confidenceThreshold: 0.75,
  },
  {
    id: "deep",
    label: "Deep",
    estimatedTime: "2 minutes",
    maxRounds: 3,
    confidenceThreshold: 0.8,
  },
  {
    id: "technical",
    label: "Technical",
    estimatedTime: "3 minutes",
    maxRounds: 5,
    confidenceThreshold: 0.9,
  },
];

export const SUGGESTED_TOPICS = [
  "Latest AI Architectures",
  "Quantum Computing Trends",
  "CRISPR Advancements",
  "Future of Autonomous Agents",
  "State of Open Source LLMs",
] as const;

export const DEFAULT_RESEARCH_MODE: ResearchMode = "deep";

export interface LiveResearchStatus {
  session_id: string;
  current_stage: string;
  progress_percent: number;
  pages_completed: number;
  pages_total: number;
  claims_extracted: number;
  validated_claims: number;
  current_url?: string | null;
  current_chunk?: number | null;
  total_chunks?: number | null;
  cpu_percent: number;
  memory_mb: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface TelemetryEventRead {
  id: string;
  session_id: string;
  timestamp: string;
  stage: string;
  event_type: string;
  message?: string | null;
  duration_ms?: number | null;
  tokens_input?: number | null;
  tokens_output?: number | null;
  url?: string | null;
  page_id?: string | null;
  query_id?: string | null;
  claim_id?: string | null;
  llm_call_id?: string | null;
  research_round?: number | null;
  metadata_json?: string | null;
  cpu_percent?: number | null;
  memory_mb?: number | null;
}

export interface ResearchMetrics {
  session_id: string;
  question: string;
  started_at?: string | null;
  finished_at?: string | null;
  total_duration_ms: number;
  query_generation_duration_ms: number;
  search_duration_ms: number;
  fetch_duration_ms: number;
  page_analysis_duration_ms: number;
  claim_extraction_duration_ms: number;
  validation_duration_ms: number;
  knowledge_duration_ms: number;
  report_duration_ms: number;
  total_pages: number;
  processed_pages: number;
  failed_pages: number;
  total_claims: number;
  validated_claims: number;
  llm_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  tokens_per_claim?: number | null;
  tokens_per_validated_claim?: number | null;
  most_expensive_stage?: string | null;
}

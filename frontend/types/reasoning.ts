export interface ReasoningValidationSummary {
  supported: number;
  weak_support: number;
  unsupported: number;
}

export interface ReasoningSourceRead {
  source_id: string;
  page_id: string;
  query_id?: string | null;
  title: string;
  url: string;
  domain: string;
  reason: string;
  quality_score: number;
  credibility_score: number;
}

export interface ReasoningRoundRead {
  round_number: number;
  title: string;
  generated_queries: string[];
  sources_visited: ReasoningSourceRead[];
  pages_analyzed: string[];
  knowledge_added: string[];
  claims_added: string[];
  validation_results: ReasoningValidationSummary;
  duration_ms: number;
  token_cost: number;
  belief_before: string;
  belief_after: string;
  what_changed: string;
  new_evidence: string[];
  contradictions: string[];
  gap_ids: string[];
  followup_ids: string[];
}

export interface ReasoningGapRead {
  id: string;
  round_number: number;
  topic: string;
  reason: string;
  priority: string;
  why_identified: string;
  followup_ids: string[];
}

export interface ReasoningFollowupRead {
  id: string;
  gap_topic: string;
  reason: string;
  priority: string;
  generated_queries: string[];
  sources_found: string[];
  knowledge_added: string[];
}

export interface ReasoningDecisionRead {
  id: string;
  kind: string;
  round_number?: number | null;
  title: string;
  reason: string;
  evidence: string[];
}

export interface ReasoningEvolutionRead {
  id: string;
  round_number: number;
  believed: string;
  changed: string;
  new_evidence: string[];
  contradictions: string[];
}

export interface ReasoningTreeNodeRead {
  id: string;
  parent_id?: string | null;
  label: string;
  kind: string;
  round_number?: number | null;
  detail?: string | null;
  order: number;
}

export interface ReasoningResponse {
  session_id: string;
  question: string;
  final_conclusions: string[];
  tree_nodes: ReasoningTreeNodeRead[];
  rounds: ReasoningRoundRead[];
  gaps: ReasoningGapRead[];
  followups: ReasoningFollowupRead[];
  decision_cards: ReasoningDecisionRead[];
  evolution: ReasoningEvolutionRead[];
}

export interface ResearchSourceRead {
    page_id: string;
    search_result_id: string;
    title: string;
    url: string;
    domain: string;
    source_type: string;
    status: string;
    analysis_status: string;
    quality_score: number;
    credibility_score: number;
    fetch_duration_ms?: number | null;
    analysis_duration_ms?: number | null;
    word_count: number;
    token_count: number;
    extraction_quality_score: number;
    summary?: string | null;
    key_claims: string[];
    entities: string[];
    relationships: string[];
    research_relevance: string;
    created_at: string;
}

export interface ResearchSourcesResponse {
    session_id: string;
    sources: ResearchSourceRead[];
}

export interface KnowledgeNodeRead {
    id: string;
    session_id: string;
    concept: string;
    description: string;
    confidence: number;
    source_count: number;
    created_at: string;
}

export interface KnowledgeEdgeRead {
    id: string;
    session_id: string;
    source_node: string;
    target_node: string;
    relationship: string;
    created_at: string;
}

export interface KnowledgeGraphResponse {
    nodes: KnowledgeNodeRead[];
    edges: KnowledgeEdgeRead[];
}
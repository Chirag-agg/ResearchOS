# ResearchOS Research Quality Analysis

## Current Research Pipeline

The ResearchOS system follows a multi-round iterative research pipeline orchestrated by the `IterativeResearchCoordinator`. Here's exactly how information flows through the system:

### Pipeline Stages (per research round):

1. **Query Generation** (LLMService.generate_queries)
   - Takes the original research question and generates 5 distinct search queries
   - Uses adapted instructions from strategy learning if available (round 0 only)

2. **Search** (SearchService.search)
   - Executes each query against SearXNG self-hosted search engine
   - Returns structured results with title, URL, snippet, engine, and score
   - Deduplicates results by URL (keeping highest score)

3. **Fetch Pages** (ScraperService.fetch_and_extract)
   - Concurrently fetches pages (limited by MAX_CONCURRENT_FETCHES)
   - Uses Playwright for dynamic content extraction and Trafilatura for text extraction
   - Stores raw HTML and extracted text, with extraction quality scoring

4. **Page Analysis** (PageUnderstandingService.analyze_page)
   - Chunks large pages (>4000 chars with 300 char overlap)
   - Extracts structured metadata per chunk: summary, key_points, main_topics, entities, importance_score
   - For multi-chunk pages, aggregates results into unified page-level analysis

5. **Knowledge Graph Construction** (KnowledgeBuilderService.build_knowledge_graph)
   - Synthesizes PageKnowledge from all successful pages into unified Knowledge Graph
   - Extracts distinct concepts as nodes (with description, confidence, source_count)
   - Creates directed relationships as edges (related_to, depends_on, supports, contrasts_with)

6. **Gap Discovery** (GapDiscoveryService.find_research_gaps)
   - Analyzes research question against existing knowledge graph
   - Identifies known_topics (well-covered concepts) and missing_topics (gaps)
   - Each gap includes topic, reason, and priority (high/medium/low)
   - Returns overall confidence score in gap analysis

7. **Followup Query Planning** (ResearchPlannerV2.generate_followup_queries)
   - Generates concrete search queries targeting identified gaps
   - Each followup query includes: query string, reason, and priority
   - Prioritizes queries that resolve high-priority gaps

8. **Execution & Metrics**
   - Calculates coverage score (known_topics / total_topics)
   - Uses gap discovery confidence as confidence score
   - Continues iterations until confidence threshold met or max rounds reached

### Supporting Services (called during pipeline):

- **Claim Extraction** (ClaimExtractor): Not directly used in the main coordinator pipeline!
  - This service extracts factual claims with evidence snippets from page content
  - Appears to be orphaned/not integrated into the main flow

- **Claim Validation** (ClaimValidator): Also not used in main pipeline
  - Validates claims against evidence snippets
  - Returns support_score and validation_status (SUPPORTED/WEAK_SUPPORT/UNSUPPORTED)

- **Strategy Learning** (StrategyLearningEngine): 
  - Learns from completed sessions to adapt future query generation
  - Classifies questions into types and remembers successful queries/domains

## Quality Bottlenecks

After analyzing the codebase, here are the top 10 bottlenecks affecting research quality, ranked by impact:

### 1. CRITICAL: Claim Extraction & Validation Not Integrated (Severity: Critical)
**Why it hurts research quality**: The system builds knowledge graphs from page summaries and topics, but never extracts and validates specific factual claims that could directly answer the research question. This means the system produces conceptual understanding rather than evidence-based answers.

**Expected quality improvement if fixed**: High - Would enable the system to ground its answers in specific, verifiable facts rather than just conceptual relationships.

**Difficulty of implementation**: Medium - Requires integrating claim extraction after page fetching and connecting it to validation, then using validated claims in gap discovery and followup planning.

### 2. CRITICAL: No Source Credibility Scoring (Severity: Critical)
**Why it hurts research quality**: All sources are treated equally regardless of authority, reliability, or relevance. A random blog post and a peer-reviewed Nature paper contribute equally to the knowledge graph, diluting research quality.

**Expected quality improvement if fixed**: High - Would enable the system to prioritize information from authoritative sources and discount low-quality information.

**Difficulty of implementation**: Medium - Could integrate domain authority scoring (via strategy learning) or content-based credibility assessment.

### 3. HIGH: Superficial Knowledge Representation (Severity: High)
**Why it hurts research quality**: Knowledge nodes represent only concepts with descriptions, not specific findings, evidence, or quantitative results. The system loses the richness of What was actually discovered in favor of conceptual taxonomies.

**Expected quality improvement if fixed**: High - Would enable the system to aggregate specific evidence rather than just concept co-occurrence.

**Difficulty of implementation**: High - Requires rewriting knowledge building to preserve evidential grounding.

### 4. HIGH: No Evidence Synthesis Across Sources (Severity: High)
**Why it hurts research quality**: The system analyzes each page independently and then builds a concept graph, but never synthesizes evidence across multiple sources to answer sub-questions or build comprehensive positions on topics.

**Expected quality improvement if fixed**: High - Would enable contradiction detection, consensus building, and evidence weighing.

**Difficulty of implementation**: High - Requires significant changes to knowledge building and gap discovery.

### 5. HIGH: Generic, Non-Evolving Queries (Severity: High)
**Why it hurts research quality**: While followup queries target gaps, they don't evolve based on what was learned in previous rounds beyond gap targeting. No query refinement based on source quality, claim validation results, or emerging patterns.

**Expected quality improvement if fixed**: Medium-High - Would enable more efficient information gathering as research progresses.

**Difficulty of implementation**: Medium - Requires enhancing research planner with learning from intermediate results.

### 6. MEDIUM: No Contradiction Detection (Severity: Medium)
**Why it hurts research quality**: The system blends all information into a unified knowledge graph without detecting when sources contradict each other, leading to conflated or inaccurate understanding.

**Expected quality improvement if fixed**: Medium - Would enable the system to identify controversies, weigh evidence, and qualify conclusions.

**Difficulty of implementation**: Medium-High - Requires comparing claims/evidence across sources.

### 7. MEDIUM: Shallow Context Understanding (Severity: Medium)
**Why it hurts research quality**: Page analysis extracts summary, topics, entities but doesn't deeply understand arguments, methodologies, or limitations presented in sources.

**Expected quality improvement if fixed**: Medium - Would enable more sophisticated evaluation of source quality and relevance.

**Difficulty of implementation**: Medium - Requires enhancing page understanding prompts and possibly multi-pass analysis.

### 8. MEDIUM: No Uncertainty Quantification in Knowledge (Severity: Medium)
**Why it hurts research quality**: Knowledge node confidence is based on LLM assessment of support in texts, not statistical aggregation of evidence quality, source reliability, or consistency across sources.

**Expected quality improvement if fixed**: Medium - Would enable better calibration of what the system knows vs. doesn't know.

**Difficulty of implementation**: Medium - Requires revising knowledge building aggregation logic.

### 9. LOW: Repetitive/Low-Value Followups (Severity: Low)
**Why it hurts research quality**: Followup queries can be repetitive or target low-value gaps because gap discovery doesn't prioritize gaps by potential impact on answering the original question.

**Expected quality improvement if fixed**: Low-Medium - Would make research more efficient by focusing on highest-impact knowledge gaps.

**Difficulty of implementation**: Low-Medium - Requires enhancing gap discovery with impact scoring.

### 10. LOW: No Research Depth Tracking (Severity: Low)
**Why it hurts research quality**: The system measures progress by concept count and coverage, not by depth of understanding or specificity of answers to the research question.

**Expected quality improvement if fixed**: Low - Would provide better signals for when deep research is complete vs. superficial.

**Difficulty of implementation**: Low - Requires adding depth metrics to evaluation.

## Comparison Against Modern Deep Research Systems

### ChatGPT Deep Research
- **What it does well**: 
  - Maintains explicit research notebook with cited facts
  - Shows reasoning trace and evidence gathering process
  - Dynamically adjusts research strategy based on findings
  - Synthesizes information into comprehensive answers with citations
- **ResearchOS missing**: 
  - Explicit fact tracking with citations
  - Reasoning trace visibility
  - Dynamic strategy adjustment based on intermediate findings
  - Final synthesis with proper attribution

### Claude Research
- **What it does well**:
  - Strong focus on evidence quality and source evaluation
  - Sophisticated contradiction detection and resolution
  - Clear distinction between established facts and hypotheses
  - Iterative deepening of understanding rather than just breadth
- **ResearchOS missing**:
  - Source credibility assessment
  - Evidence-weighted knowledge representation
  - Explicit handling of conflicting information
  - Hypothesis tracking and testing

### Gemini Deep Research
- **What it does well**:
  - Multimodal evidence integration (when applicable)
  - Strong emphasis on comprehensive coverage assessment
  - Sophisticated query evolution and narrowing
  - Clear output formatting with evidence mapping
- **ResearchOS missing**:
  - Comprehensive evidence mapping to final answers
  - Sophisticated query evolution beyond gap-targeting
  - Exhaustive coverage assessment methodologies

### Key Missing Capabilities in ResearchOS:
1. **Evidence grounding**: No mechanism to trace conclusions back to specific evidence snippets
2. **Source authority weighting**: All sources treated equally in knowledge construction
3. **Contradiction resolution**: No detection or handling of conflicting information
4. **Research traceability**: No explicit research notebook showing how conclusions were reached
5. **Evidence synthesis**: No aggregation of multiple sources to answer sub-questions
6. **Uncertainty quantification**: No calibrated confidence in what is known vs. unknown
7. **Dynamic query refinement**: Queries evolve only via gap targeting, not learning from intermediate results

## Highest ROI Improvements (One Week Effort)

If only one week of engineering effort were available, here are the top improvements ranked by ROI:

### 1. Integrate Claim Extraction & Validation (Highest ROI)
**What to do**: 
- Connect ClaimExtractor after page fetching in the coordinator
- Run ClaimValidator on extracted claims with evidence snippets
- Store validated claims (SUPPORTED/WEAK_SUPPORT) with their evidence
- Modify knowledge building to use claims rather than just page summaries
- Update gap discovery to analyze claim coverage rather than just concept coverage

**Why highest ROI**: 
- Transforms system from conceptual mapper to evidence-grounded reasoning engine
- Enables actual question answering rather than topic mapping
- Leverages existing, well-written claim extraction/validation code
- Addresses the Core problem: "Extracts generic facts instead of answering the research question"

### 2. Implement Source Credibility Scoring (High ROI)
**What to do**:
- Enhance StrategyLearningEngine to track domain authority based on validation outcomes
- Add domain reputation scoring (e.g., .edu/.gov > established orgs > blogs)
- Modify knowledge building to weight nodes/edges by source credibility
- Adjust gap discovery to prioritize filling gaps in high-credibility areas

**Why high ROI**:
- Addresses: "Treats weak sources similarly to strong sources"
- Builds on existing strategy learning infrastructure
- Significant quality improvement with moderate implementation effort

### 3. Enhance Knowledge Graph to Include Evidence (High ROI)
**What to do**:
- Extend KnowledgeNode to include supporting claims/evidence (not just counts)
- Modify knowledge building to aggregate specific evidence rather than just concept descriptions
- Update gap discovery to analyze evidence depth, not just concept presence
- Consider adding evidence-type distinctions (measurement, observation, testimony, etc.)

**Why high ROI**:
- Addresses: "Produces knowledge graphs containing concepts rather than findings"
- Makes the knowledge base actually useful for answering specific questions
- Builds on existing knowledge graph infrastructure

### 4. Add Basic Contradiction Detection (Medium ROI)
**What to do**:
- During claim validation, flag claims with conflicting evidence snippets
- Create contradiction nodes/edges in knowledge graph
- Modify followup planning to prioritize resolving high-credibility contradictions
- Add contradiction metrics to research evaluation

**Why medium ROI**:
- Addresses: "Fails to deeply synthesize evidence across sources"
- Relatively straightforward to implement with existing validation
- Significant improvement in research rigor

## Implementation Roadmap

### Phase A (Highest Impact - Days 1-2)
1. **Integrate Claim Pipeline**
   - Modify `IterativeResearchCoordinator` to call `ClaimExtractor` after page fetching
   - Add `ClaimValidator` calls for extracted claims
   - Store validated claims with evidence snippets and support scores
   - Connect validated claims to knowledge building process

### Phase B (High Impact - Days 3-4)
2. **Add Source Credibility**
   - Enhance `StrategyLearningEngine` to track domain-based validation outcomes
   - Implement simple domain authority scoring (TLD, known authority lists)
   - Modify `KnowledgeBuilderService` to weight concepts by source credibility
   - Update `GapDiscoveryService` to consider source credibility in gap prioritization

### Phase C (Medium Impact - Days 5)
3. **Enhance Knowledge Representation**
   - Extend `KnowledgeNode` model to include supporting evidence references
   - Modify knowledge building to aggregate claims, not just concept counts
   - Update gap discovery to analyze evidence depth and consistency
   - Add evidence-weighted metrics to research evaluation

### Phase D (Lower Impact - Day 6-7)
4. **Add Contradiction Detection**
   - Modify claim validation to detect conflicting evidence for similar claims
   - Create contradiction tracking in knowledge graph
   - Enhance followup planning to prioritize contradiction resolution
   - Add contradiction metrics to research reporting

### Ongoing Throughout:
- Update unit tests for modified services
- Add integration tests for new pipeline connections
- Update documentation in CLAUDE.md and service docstrings

## Recommendation: Which Subsystem to Rewrite First

**The `IterativeResearchCoordinator` should be modified first (not rewritten) to integrate the claim extraction and validation pipeline.**

**Why this subsystem first**:
1. **Highest Impact**: This is the orchestrator - modifying it connects the orphaned claim services to the main research flow
2. **Leverages Existing Code**: The claim extraction and validation services are already well-implemented; they just need to be connected
3. **Addresses Core Problem**: Directly solves "Extracts generic facts instead of answering the research question"
4. **Enables All Other Improvements**: Once claims are flowing through the system, source credibility, evidence synthesis, and contradiction detection all become possible and more effective
5. **Lower Risk**: Rather than rewriting, we're extending the existing proven orchestration logic
6. **Immediate Value**: Even basic claim integration would significantly improve the system's ability to provide evidence-based answers rather than just conceptual maps

The claim extraction and validation services exist and are sophisticated - they're simply not connected to the main research pipeline. By modifying the coordinator to:
1. Extract claims from fetched pages (after scraping, before page understanding)
2. Validate those claims against their evidence snippets
3. Pass validated claims to knowledge building (instead of or alongside page summaries)
4. Use claim coverage in gap discovery (instead of or alongside concept coverage)

...we would transform ResearchOS from a concept-mapping system into an evidence-grounded reasoning engine capable of actually answering research questions with cited evidence - which is the core deficiency identified in the problem statement.
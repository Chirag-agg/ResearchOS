"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronRight, Clock3, GitBranch, Layers3, Search, Sparkles, Target, CircleDot } from "lucide-react";
import { cn } from "@/lib/utils";
import { getResearchReasoning } from "@/lib/api";
import type { ReasoningDecisionRead, ReasoningEvolutionRead, ReasoningFollowupRead, ReasoningGapRead, ReasoningResponse, ReasoningRoundRead, ReasoningTreeNodeRead } from "@/types/reasoning";

interface ReasoningWorkspaceProps {
  sessionId: string;
}

interface TreeBranchProps {
  node: ReasoningTreeNodeRead;
  childrenByParent: Map<string, ReasoningTreeNodeRead[]>;
  depth?: number;
}

function StatCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-md">
      <div className="text-[11px] uppercase tracking-[0.2em] text-white/45">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-white/50">{hint}</div> : null}
    </div>
  );
}

function SectionCard({ title, subtitle, icon, children }: { title: string; subtitle?: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-5 shadow-2xl shadow-black/30 backdrop-blur-xl">
      <div className="flex items-center gap-3 border-b border-white/10 pb-4">
        {icon ? <div className="rounded-xl border border-white/10 bg-white/5 p-2 text-white/70">{icon}</div> : null}
        <div>
          <div className="text-xs uppercase tracking-[0.28em] text-white/45">{title}</div>
          {subtitle ? <div className="mt-1 text-sm text-white/55">{subtitle}</div> : null}
        </div>
      </div>
      <div className="pt-4">{children}</div>
    </div>
  );
}

function TreeBranch({ node, childrenByParent, depth = 0 }: TreeBranchProps) {
  const children = childrenByParent.get(node.id) ?? [];
  const isRound = node.kind === "round";
  const isRoot = node.kind === "question";

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-white/10 pl-4") }>
      <div
        className={cn(
          "rounded-2xl border p-4 transition-colors",
          isRoot ? "border-sky-400/25 bg-sky-500/10" : isRound ? "border-primary/30 bg-primary/10" : "border-white/10 bg-white/5"
        )}
      >
        <div className="flex items-start gap-3">
          <div className={cn("mt-0.5 rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.2em]", isRoot ? "border-sky-400/30 bg-sky-500/15 text-sky-100" : isRound ? "border-primary/30 bg-primary/15 text-primary" : "border-white/10 bg-black/20 text-white/55")}>
            {node.kind.replace(/_/g, " ")}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              {depth > 0 ? <ChevronRight className="h-4 w-4 text-white/35" /> : null}
              <span className="truncate">{node.label}</span>
            </div>
            {node.detail ? <div className="mt-1 text-sm leading-6 text-white/60">{node.detail}</div> : null}
          </div>
        </div>
      </div>

      {children.length > 0 ? (
        <div className="mt-3 space-y-3">
          {children.map((child) => (
            <TreeBranch key={child.id} node={child} childrenByParent={childrenByParent} depth={depth + 1} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ValidationPill({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={cn("rounded-full border px-3 py-1 text-xs font-medium", tone)}>
      {label}: {value}
    </div>
  );
}

function DecisionCard({ decision, active }: { decision: ReasoningDecisionRead; active: boolean }) {
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 transition-colors",
        active ? "border-primary/40 bg-primary/10" : "border-white/10 bg-black/15 hover:border-white/20 hover:bg-white/10"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-white/40">{decision.kind.replace(/_/g, " ")}</div>
          <div className="mt-1 text-sm font-semibold text-white">{decision.title}</div>
        </div>
        {typeof decision.round_number === "number" ? (
          <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-[11px] text-white/65">Round {decision.round_number}</span>
        ) : null}
      </div>
      <div className="mt-3 text-sm leading-6 text-white/65">{decision.reason}</div>
      {decision.evidence.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {decision.evidence.map((item) => (
            <span key={item} className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/65">
              {item}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RoundExplorer({ round, onSelect }: { round: ReasoningRoundRead; onSelect: (roundNumber: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(round.round_number)}
      className="w-full rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/20 hover:bg-white/10"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-white/40">{round.title}</div>
          <div className="mt-1 text-sm font-semibold text-white">{round.belief_after}</div>
        </div>
        <div className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-[11px] text-white/65">{Math.round(round.duration_ms)} ms</div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-white/60">
        <span className="rounded-full border border-white/10 px-2 py-1">{round.generated_queries.length} queries</span>
        <span className="rounded-full border border-white/10 px-2 py-1">{round.sources_visited.length} sources</span>
        <span className="rounded-full border border-white/10 px-2 py-1">{round.knowledge_added.length} knowledge</span>
        <span className="rounded-full border border-white/10 px-2 py-1">{round.gap_ids.length} gaps</span>
      </div>
    </button>
  );
}

function HighlightList({ items, emptyLabel }: { items: string[]; emptyLabel: string }) {
  if (!items.length) {
    return <div className="text-sm text-white/55">{emptyLabel}</div>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span key={item} className="rounded-full border border-white/10 bg-black/15 px-3 py-1 text-xs text-white/70">
          {item}
        </span>
      ))}
    </div>
  );
}

function ReasoningRoundDetail({ round }: { round: ReasoningRoundRead }) {
  return (
    <div className="space-y-4 rounded-3xl border border-white/10 bg-black/20 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.25em] text-white/45">Round Explorer</div>
          <div className="mt-2 text-2xl font-semibold text-white">{round.title}</div>
          <div className="mt-1 text-sm text-white/55">{round.what_changed}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-white/70">
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">Duration {Math.round(round.duration_ms)} ms</div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">Tokens {round.token_cost}</div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">Coverage {round.validation_results.supported + round.validation_results.weak_support + round.validation_results.unsupported}</div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">Claims {round.claims_added.length}</div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Queries" value={round.generated_queries.length} hint={round.generated_queries[0] ?? "No queries"} />
        <StatCard label="Sources" value={round.sources_visited.length} hint={round.sources_visited[0]?.title ?? "No sources"} />
        <StatCard label="Knowledge" value={round.knowledge_added.length} hint={round.knowledge_added[0] ?? "No concepts"} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Generated Queries</div>
          <div className="mt-3 space-y-2">
            {round.generated_queries.length ? round.generated_queries.map((query) => (
              <div key={query} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/75">{query}</div>
            )) : <div className="text-sm text-white/55">No queries recorded.</div>}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Sources Visited</div>
          <div className="mt-3 space-y-2">
            {round.sources_visited.length ? round.sources_visited.map((source) => (
              <div key={source.source_id} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/75">
                <div className="font-medium text-white">{source.title}</div>
                <div className="mt-1 text-xs text-white/45">{source.domain} · {Math.round(source.quality_score * 100)}% quality</div>
                <div className="mt-2 text-xs text-white/60">Why: {source.reason}</div>
              </div>
            )) : <div className="text-sm text-white/55">No sources were matched to this round.</div>}
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Pages Analyzed</div>
          <div className="mt-3 space-y-2">
            {round.pages_analyzed.length ? round.pages_analyzed.map((page) => (
              <div key={page} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/70">{page}</div>
            )) : <div className="text-sm text-white/55">No analyzed pages were linked to this round.</div>}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Knowledge Added</div>
          <div className="mt-3 space-y-2">
            {round.knowledge_added.length ? round.knowledge_added.map((item) => (
              <div key={item} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/70">{item}</div>
            )) : <div className="text-sm text-white/55">No knowledge nodes were recorded from this round.</div>}
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Claims Added</div>
          <div className="mt-3 space-y-2">
            {round.claims_added.length ? round.claims_added.map((claim) => (
              <div key={claim} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/70">{claim}</div>
            )) : <div className="text-sm text-white/55">No claims were recorded for this round.</div>}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Validation Results</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <ValidationPill label="Supported" value={round.validation_results.supported} tone="border-emerald-500/25 bg-emerald-500/10 text-emerald-100" />
            <ValidationPill label="Weak" value={round.validation_results.weak_support} tone="border-amber-500/25 bg-amber-500/10 text-amber-100" />
            <ValidationPill label="Unsupported" value={round.validation_results.unsupported} tone="border-rose-500/25 bg-rose-500/10 text-rose-100" />
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">What the agent believed</div>
          <div className="mt-2 text-sm leading-6 text-white/70">{round.belief_before}</div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">How it changed</div>
          <div className="mt-2 text-sm leading-6 text-white/70">{round.belief_after}</div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div className="text-xs uppercase tracking-[0.22em] text-white/45">Contradictions and new evidence</div>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div>
            <div className="text-sm font-semibold text-white">New evidence</div>
            <div className="mt-2 space-y-2">{round.new_evidence.length ? round.new_evidence.map((item) => <div key={item} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/70">{item}</div>) : <div className="text-sm text-white/55">No new evidence captured.</div>}</div>
          </div>
          <div>
            <div className="text-sm font-semibold text-white">Contradictions</div>
            <div className="mt-2 space-y-2">{round.contradictions.length ? round.contradictions.map((item) => <div key={item} className="rounded-xl border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/70">{item}</div>) : <div className="text-sm text-white/55">No explicit contradictions were preserved in this round.</div>}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function GapCard({ gap, active, onSelect }: { gap: ReasoningGapRead; active: boolean; onSelect: (gapId: string) => void }) {
  const priorityTone = gap.priority === "high" ? "border-rose-500/25 bg-rose-500/10 text-rose-100" : gap.priority === "medium" ? "border-amber-500/25 bg-amber-500/10 text-amber-100" : "border-sky-500/25 bg-sky-500/10 text-sky-100";

  return (
    <button
      type="button"
      onClick={() => onSelect(gap.id)}
      className={cn("w-full rounded-2xl border p-4 text-left transition-colors", active ? "border-primary/40 bg-primary/10" : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10")}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">{gap.topic}</div>
          <div className="mt-1 text-sm text-white/60">{gap.reason}</div>
        </div>
        <span className={cn("rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.18em]", priorityTone)}>{gap.priority}</span>
      </div>
      <div className="mt-3 text-xs text-white/45">Followups: {gap.followup_ids.length}</div>
    </button>
  );
}

function FollowupCard({ followup }: { followup: ReasoningFollowupRead }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-white/40">{followup.gap_topic}</div>
          <div className="mt-1 text-sm font-semibold text-white">{followup.reason}</div>
        </div>
        <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-[11px] text-white/65">{followup.priority}</span>
      </div>
      <div className="mt-3 space-y-3 text-sm text-white/70">
        <div>
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Generated Queries</div>
          <HighlightList items={followup.generated_queries} emptyLabel="No followup queries were matched." />
        </div>
        <div>
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Sources Found</div>
          <HighlightList items={followup.sources_found} emptyLabel="No sources were linked to this followup." />
        </div>
        <div>
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Knowledge Added</div>
          <HighlightList items={followup.knowledge_added} emptyLabel="No knowledge was linked to this followup." />
        </div>
      </div>
    </div>
  );
}

function EvolutionCard({ evolution }: { evolution: ReasoningEvolutionRead }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-white/40">Round {evolution.round_number}</div>
          <div className="mt-1 text-sm font-semibold text-white">What the agent believed</div>
        </div>
        <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1 text-[11px] text-white/65">Evolution</span>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-black/15 p-3">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Believed</div>
          <div className="mt-1 text-sm text-white/70">{evolution.believed}</div>
        </div>
        <div className="rounded-xl border border-white/10 bg-black/15 p-3">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Changed</div>
          <div className="mt-1 text-sm text-white/70">{evolution.changed}</div>
        </div>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-black/15 p-3">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">New Evidence</div>
          <HighlightList items={evolution.new_evidence} emptyLabel="No new evidence captured." />
        </div>
        <div className="rounded-xl border border-white/10 bg-black/15 p-3">
          <div className="text-xs uppercase tracking-[0.22em] text-white/45">Contradictions</div>
          <HighlightList items={evolution.contradictions} emptyLabel="No contradictions captured." />
        </div>
      </div>
    </div>
  );
}

export function ReasoningWorkspace({ sessionId }: ReasoningWorkspaceProps) {
  const [reasoning, setReasoning] = useState<ReasoningResponse | null>(null);
  const [selectedRoundNumber, setSelectedRoundNumber] = useState<number | null>(null);
  const [selectedGapId, setSelectedGapId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadReasoning() {
      try {
        const response = await getResearchReasoning(sessionId);
        if (!mounted) return;
        setReasoning(response);
        setError(null);
        setSelectedRoundNumber((current) => current ?? response.rounds[0]?.round_number ?? null);
        setSelectedGapId((current) => current ?? response.gaps[0]?.id ?? null);
      } catch (loadError) {
        console.error("Failed to load reasoning trail", loadError);
        if (mounted) setError("Failed to load reasoning trail.");
      }
    }

    loadReasoning();
    const interval = setInterval(loadReasoning, 5000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [sessionId]);

  const childrenByParent = useMemo(() => {
    const map = new Map<string, ReasoningTreeNodeRead[]>();
    if (!reasoning) return map;

    const nodes = [...reasoning.tree_nodes].sort((left, right) => left.order - right.order);
    for (const node of nodes) {
      const parentKey = node.parent_id ?? "";
      const list = map.get(parentKey) ?? [];
      list.push(node);
      map.set(parentKey, list);
    }
    return map;
  }, [reasoning]);

  const selectedRound = reasoning?.rounds.find((round) => round.round_number === selectedRoundNumber) ?? reasoning?.rounds[0] ?? null;
  const selectedGap = reasoning?.gaps.find((gap) => gap.id === selectedGapId) ?? reasoning?.gaps[0] ?? null;
  const selectedFollowups = reasoning?.followups.find((followup) => followup.id === selectedGap?.id) ?? null;
  const selectedDecisionCards = reasoning?.decision_cards.filter((decision) => !selectedRound || !decision.round_number || decision.round_number === selectedRound.round_number) ?? [];

  if (error && !reasoning) {
    return <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-6 text-red-200">{error}</div>;
  }

  if (!reasoning) {
    return <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-white/60">Loading reasoning trail...</div>;
  }

  return (
    <div className="space-y-6 text-white">
      <div className="flex flex-col gap-4 border-b border-white/10 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-white/45">
            <GitBranch className="h-4 w-4" /> Reasoning
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">How the agent thought</h1>
          <p className="mt-2 max-w-3xl text-sm text-white/55">
            Follow the decision trail from question to rounds, understand why each query was generated, why gaps appeared, and how the final conclusion formed.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-white/65">
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">{reasoning.rounds.length} rounds</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">{reasoning.gaps.length} gaps</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">{reasoning.followups.length} followups</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">{reasoning.decision_cards.length} decisions</span>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Rounds" value={reasoning.rounds.length} hint={reasoning.rounds[0]?.title ?? "No rounds yet"} />
        <StatCard label="Gaps" value={reasoning.gaps.length} hint={reasoning.gaps[0]?.topic ?? "No gaps yet"} />
        <StatCard label="Followups" value={reasoning.followups.length} hint={reasoning.followups[0]?.gap_topic ?? "No followups yet"} />
        <StatCard label="Final Conclusions" value={reasoning.final_conclusions.length} hint={reasoning.final_conclusions[0] ?? "No conclusion captured"} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <SectionCard title="Research Tree" subtitle="Question → rounds → decisions → conclusion" icon={<Layers3 className="h-4 w-4" />}>
          <div className="max-h-[78vh] space-y-4 overflow-y-auto pr-2">
            {(childrenByParent.get("") ?? []).map((node) => (
              <TreeBranch key={node.id} node={node} childrenByParent={childrenByParent} />
            ))}
          </div>
        </SectionCard>

        <div className="space-y-6">
          <SectionCard title="Round Explorer" subtitle="Click a round to inspect decisions and evidence" icon={<Clock3 className="h-4 w-4" />}>
            <div className="max-h-[28rem] space-y-3 overflow-y-auto pr-1">
              {reasoning.rounds.map((round) => (
                <RoundExplorer key={round.round_number} round={round} onSelect={setSelectedRoundNumber} />
              ))}
            </div>
            {selectedRound ? (
              <div className="mt-4">
                <ReasoningRoundDetail round={selectedRound} />
              </div>
            ) : null}
          </SectionCard>

          <SectionCard title="Gap Explorer" subtitle="Every discovered gap and why it mattered" icon={<Target className="h-4 w-4" />}>
            <div className="max-h-[24rem] space-y-3 overflow-y-auto pr-1">
              {reasoning.gaps.length ? reasoning.gaps.map((gap) => (
                <GapCard key={gap.id} gap={gap} active={gap.id === selectedGap?.id} onSelect={setSelectedGapId} />
              )) : <div className="text-sm text-white/55">No gaps were discovered.</div>}
            </div>
          </SectionCard>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Followup Explorer" subtitle="Gap → followup queries → sources → knowledge" icon={<Search className="h-4 w-4" />}>
          {selectedFollowups ? (
            <FollowupCard followup={selectedFollowups} />
          ) : (
            <div className="text-sm text-white/55">Select a gap to inspect its followup queries.</div>
          )}
          <div className="mt-4 space-y-3">
            {reasoning.followups.map((followup) => (
              <FollowupCard key={followup.id} followup={followup} />
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Decision Cards" subtitle="Why the agent acted" icon={<Sparkles className="h-4 w-4" />}>
          <div className="max-h-[46rem] space-y-3 overflow-y-auto pr-1">
            {selectedDecisionCards.length ? selectedDecisionCards.map((decision) => (
              <DecisionCard key={decision.id} decision={decision} active={decision.round_number === selectedRound?.round_number} />
            )) : <div className="text-sm text-white/55">No decision cards available for the selected round.</div>}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Research Evolution" subtitle="Belief changes, new evidence, and contradictions over time" icon={<CircleDot className="h-4 w-4" />}>
        <div className="space-y-3">
          {reasoning.evolution.length ? reasoning.evolution.map((item: ReasoningEvolutionRead) => (
            <EvolutionCard key={item.id} evolution={item} />
          )) : <div className="text-sm text-white/55">No evolution data recorded yet.</div>}
        </div>
      </SectionCard>

      <SectionCard title="Final Conclusions" subtitle="Why the agent ended where it did" icon={<GitBranch className="h-4 w-4" />}>
        <div className="space-y-3">
          {reasoning.final_conclusions.length ? reasoning.final_conclusions.map((conclusion) => (
            <div key={conclusion} className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-white/70">
              {conclusion}
            </div>
          )) : <div className="text-sm text-white/55">No final conclusions were captured.</div>}
        </div>
      </SectionCard>
    </div>
  );
}

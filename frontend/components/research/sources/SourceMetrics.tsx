"use client";

interface SourceMetricsProps {
    total: number;
    analyzed: number;
    highQuality: number;
    lowQuality: number;
}

function Metric({ label, value }: { label: string; value: string | number }) {
    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-md">
            <div className="text-[11px] uppercase tracking-[0.2em] text-white/45">{label}</div>
            <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
        </div>
    );
}

export function SourceMetrics({ total, analyzed, highQuality, lowQuality }: SourceMetricsProps) {
    return (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Metric label="Sources" value={total} />
            <Metric label="Analyzed" value={analyzed} />
            <Metric label="High Quality" value={highQuality} />
            <Metric label="Low Quality" value={lowQuality} />
        </div>
    );
}
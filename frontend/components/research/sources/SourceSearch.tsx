"use client";

interface SourceSearchProps {
    value: string;
    onChange: (value: string) => void;
}

export function SourceSearch({ value, onChange }: SourceSearchProps) {
    return (
        <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/70 backdrop-blur-md">
            <span className="text-white/40">Search</span>
            <input
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder="title, domain, url, claim text"
                className="w-full bg-transparent text-sm text-white outline-none placeholder:text-white/30"
            />
        </label>
    );
}
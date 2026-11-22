"use client";

import { useEffect, useState } from "react";

import { readPresenceApiV1PbxPresenceGet } from "@/client/sdk.gen";
import { cn } from "@/lib/utils";

export type PresenceState = "available" | "on_call" | "ringing" | "dnd" | "away" | "offline" | "unknown";
export type Presence = { state: PresenceState; label: string; status: string };
export type TeamPresence = { live: boolean; extensions: Record<string, Presence> };

const DOT: Record<PresenceState, string> = {
    available: "bg-emerald-500",
    on_call: "bg-red-500",
    ringing: "bg-red-500 animate-pulse",
    dnd: "bg-red-500 ring-2 ring-inset ring-white/70",
    away: "bg-amber-400",
    offline: "bg-muted-foreground/50",
    unknown: "bg-muted-foreground/30",
};

/** Presence of every extension, refreshed every ``everyMs`` while mounted. */
export function useTeamPresence(everyMs = 20_000): TeamPresence | null {
    const [presence, setPresence] = useState<TeamPresence | null>(null);
    useEffect(() => {
        let alive = true;
        const load = async () => {
            const response = await readPresenceApiV1PbxPresenceGet();
            if (alive && !response.error) setPresence(response.data as unknown as TeamPresence);
        };
        void load();
        const timer = setInterval(() => void load(), everyMs);
        return () => {
            alive = false;
            clearInterval(timer);
        };
    }, [everyMs]);
    return presence;
}

export function PresenceBadge({ presence }: { presence?: Presence }) {
    if (!presence || presence.state === "unknown") return <span className="text-muted-foreground">—</span>;
    return (
        <span className="inline-flex items-center gap-2 text-sm" data-testid="presence" title={presence.status || undefined}>
            <span className={cn("size-2.5 shrink-0 rounded-full", DOT[presence.state])} aria-hidden />
            {presence.label}
            {presence.status && <span className="max-w-48 truncate text-xs text-muted-foreground">· {presence.status}</span>}
        </span>
    );
}

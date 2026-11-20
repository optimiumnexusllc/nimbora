"use client";

/**
 * AI -> human handoff card: what the AI agent learned before transferring the
 * caller. Shown in the softphone the moment the call rings, so the human never
 * has to ask the customer to start over. The AI summary may arrive a few
 * seconds after the card (it is generated in the background).
 */
import { Bot, ChevronDown, ChevronUp, Loader2, Sparkles, User } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { Handoff } from "@/lib/enterpriseApi";
import { cn } from "@/lib/utils";

const SENTIMENT: Record<NonNullable<Handoff["sentiment"]>, { label: string; className: string }> = {
    positive: { label: "Satisfait", className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
    neutral: { label: "Neutre", className: "bg-slate-500/15 text-slate-300 border-slate-500/30" },
    frustrated: { label: "Agacé", className: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
    angry: { label: "En colère", className: "bg-red-500/15 text-red-400 border-red-500/30" },
};

function humanize(key: string): string {
    const text = key.replace(/[_-]+/g, " ").trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function renderValue(value: unknown): string {
    if (typeof value === "boolean") return value ? "Oui" : "Non";
    if (typeof value === "string" || typeof value === "number") return String(value);
    return JSON.stringify(value);
}

export function HandoffCard({ handoff }: { handoff: Handoff }) {
    const [showTranscript, setShowTranscript] = useState(false);
    const sentiment = handoff.sentiment ? SENTIMENT[handoff.sentiment] : null;
    const data = Object.entries(handoff.collected_data ?? {});

    return (
        <div className="handoff-card relative overflow-hidden rounded-xl border border-brand-violet/30 bg-gradient-to-br from-brand-violet/10 via-transparent to-brand-cyan/10 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
                <Sparkles className="size-4 text-brand-cyan" />
                <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                    Passation de l&apos;agent IA
                </span>
                {handoff.queue_slug && <Badge variant="secondary">file {handoff.queue_slug}</Badge>}
                {sentiment && (
                    <span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", sentiment.className)}>
                        {sentiment.label}
                    </span>
                )}
            </div>

            <div className="mb-3 flex items-center gap-2 text-sm">
                <User className="size-4 text-muted-foreground" />
                <span className="font-medium">{handoff.customer_name || "Client"}</span>
                {handoff.caller_number && (
                    <span className="font-mono text-muted-foreground">{handoff.caller_number}</span>
                )}
            </div>

            {handoff.summary_status === "pending" ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" /> L&apos;IA prépare le résumé de l&apos;appel…
                </p>
            ) : (
                <div className="space-y-2 text-sm">
                    {handoff.reason && (
                        <p>
                            <span className="text-muted-foreground">Motif : </span>
                            <span className="font-medium">{handoff.reason}</span>
                        </p>
                    )}
                    {handoff.summary && <p>{handoff.summary}</p>}
                    {handoff.next_step && (
                        <p className="rounded-lg border border-brand-cyan/30 bg-brand-cyan/10 px-3 py-2">
                            <span className="font-semibold text-brand-cyan">À faire en premier : </span>
                            {handoff.next_step}
                        </p>
                    )}
                </div>
            )}

            {data.length > 0 && (
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                    {data.map(([key, value]) => (
                        <div key={key} className="min-w-0">
                            <dt className="truncate text-xs text-muted-foreground">{humanize(key)}</dt>
                            <dd className="truncate font-medium">{renderValue(value)}</dd>
                        </div>
                    ))}
                </dl>
            )}

            {handoff.transcript.length > 0 && (
                <div className="mt-3">
                    <button
                        type="button"
                        onClick={() => setShowTranscript((v) => !v)}
                        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                        {showTranscript ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
                        Conversation avec l&apos;IA ({handoff.transcript.length} échanges)
                    </button>
                    {showTranscript && (
                        <ol className="mt-2 max-h-64 space-y-2 overflow-y-auto pr-1 text-sm">
                            {handoff.transcript.map((turn, i) => (
                                <li
                                    key={i}
                                    className={cn(
                                        "flex gap-2 rounded-lg px-3 py-2",
                                        turn.speaker === "client" ? "bg-muted/60" : "bg-brand-violet/10",
                                    )}
                                >
                                    {turn.speaker === "client" ? (
                                        <User className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                                    ) : (
                                        <Bot className="mt-0.5 size-3.5 shrink-0 text-brand-violet" />
                                    )}
                                    <span>{turn.text}</span>
                                </li>
                            ))}
                        </ol>
                    )}
                </div>
            )}
        </div>
    );
}

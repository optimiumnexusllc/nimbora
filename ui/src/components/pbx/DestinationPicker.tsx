"use client";

import type { WorkflowSummaryResponse } from "@/client/types.gen";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type { PbxQueue, PbxUser } from "./types";

export type DestinationType = "queue" | "group" | "user" | "ai" | "voicemail" | "menu" | "conference" | "hangup";
export type Destination = { type: DestinationType; target_id: number | null };
export type PbxVoicemail = { id: number; name: string; number: string | null };
export type MenuOption = { id: number; name: string; published: boolean };
export type NamedTarget = { id: number; name: string; extensions?: string[] };

export const DESTINATION_LABELS: Record<DestinationType, string> = {
    ai: "Agent IA",
    queue: "File d'attente",
    group: "Groupe d'appel",
    user: "Poste",
    voicemail: "Messagerie",
    menu: "Autre menu vocal",
    conference: "Salle de conférence",
    hangup: "Raccrocher",
};

export type DestinationSources = {
    queues: PbxQueue[];
    users: PbxUser[];
    voicemails: PbxVoicemail[];
    workflows: WorkflowSummaryResponse[];
    menus: MenuOption[];
    aiEnabled: boolean;
    groups?: NamedTarget[];
    conferences?: NamedTarget[];
};

const named = (items: NamedTarget[] | undefined) =>
    (items ?? []).map((t) => ({ id: t.id, label: `${t.name}${t.extensions?.[0] ? ` (${t.extensions[0]})` : ""}` }));

export function targetsFor(type: DestinationType, sources: DestinationSources): { id: number; label: string }[] {
    switch (type) {
        case "queue":
            return sources.queues.map((q) => ({ id: q.id, label: `${q.name}${q.extensions[0] ? ` (${q.extensions[0]})` : ""}` }));
        case "user":
            return sources.users
                .filter((u) => u.id != null)
                .map((u) => ({ id: u.id as number, label: `${u.name}${u.extension ? ` (${u.extension})` : ""}` }));
        case "voicemail":
            return sources.voicemails.map((v) => ({ id: v.id, label: `${v.name}${v.number ? ` (${v.number})` : ""}` }));
        case "ai":
            return sources.workflows.map((w) => ({ id: w.id, label: w.name }));
        case "group":
            return named(sources.groups);
        case "conference":
            return named(sources.conferences);
        case "menu":
            return sources.menus.map((m) => ({ id: m.id, label: m.published ? m.name : `${m.name} (non publié)` }));
        default:
            return [];
    }
}

export function describeDestination(destination: Destination, sources: DestinationSources): string {
    if (destination.type === "hangup") return DESTINATION_LABELS.hangup;
    const target = targetsFor(destination.type, sources).find((t) => t.id === destination.target_id);
    return `${DESTINATION_LABELS[destination.type]} · ${target?.label ?? "à choisir"}`;
}

export function DestinationPicker({
    value,
    onChange,
    sources,
    label,
    excludeMenuId,
    allowed,
    className,
}: {
    value: Destination;
    onChange: (value: Destination) => void;
    sources: DestinationSources;
    label: string;
    excludeMenuId?: number;
    allowed?: DestinationType[];
    className?: string;
}) {
    const types = (allowed ?? (Object.keys(DESTINATION_LABELS) as DestinationType[])).filter(
        (t) =>
            (t !== "ai" || sources.aiEnabled) &&
            (t !== "group" || (sources.groups ?? []).length > 0) &&
            (t !== "conference" || (sources.conferences ?? []).length > 0),
    );
    const targets = targetsFor(value.type, sources).filter((t) => value.type !== "menu" || t.id !== excludeMenuId);
    return (
        <div className={cn("grid min-w-0 gap-2 sm:grid-cols-[160px_minmax(0,1fr)]", className)}>
            <Select
                value={value.type}
                onValueChange={(type) => {
                    const next = type as DestinationType;
                    const first = targetsFor(next, sources).filter((t) => next !== "menu" || t.id !== excludeMenuId)[0];
                    onChange({ type: next, target_id: next === "hangup" ? null : (first?.id ?? null) });
                }}
            >
                <SelectTrigger aria-label={`${label} — type`} className="w-full">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {types.map((t) => (
                        <SelectItem key={t} value={t}>
                            {DESTINATION_LABELS[t]}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            {value.type !== "hangup" &&
                (targets.length === 0 ? (
                    <p className="self-center text-sm text-muted-foreground">Aucun élément disponible.</p>
                ) : (
                    <Select
                        value={value.target_id != null ? String(value.target_id) : ""}
                        onValueChange={(id) => onChange({ ...value, target_id: Number(id) })}
                    >
                        <SelectTrigger aria-label={`${label} — cible`} className="w-full min-w-0">
                            <SelectValue placeholder="Choisir" />
                        </SelectTrigger>
                        <SelectContent>
                            {targets.map((t) => (
                                <SelectItem key={t.id} value={String(t.id)}>
                                    {t.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                ))}
        </div>
    );
}

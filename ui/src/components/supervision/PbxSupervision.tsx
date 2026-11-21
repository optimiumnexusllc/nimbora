"use client";

import { AlertTriangle, BellRing, Bot, Ear, Headphones, Mic, Pause, PhoneCall, Play, Settings2, ShieldAlert, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { agentActionApiV1PbxAgentsAgentNumberActionPost, spyApiV1PbxSupervisionSpyPost } from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";

import { formatDuration } from "./format";
import type { HandoffCard, PbxCall, PbxLive, PbxLiveAgent, SpyMode } from "./types";
import { SENTIMENT_LABELS, SPY_LABELS } from "./types";

export type Extension = { uuid: string; name: string; extension: string | null };

const AGENT_STATE: Record<PbxLiveAgent["state"], { label: string; className: string }> = {
    available: { label: "Disponible", className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" },
    on_call: { label: "En appel", className: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" },
    ringing: { label: "Sonne", className: "bg-violet-500/15 text-violet-300 border-violet-500/30" },
    paused: { label: "En pause", className: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
    logged_out: { label: "Déconnecté", className: "bg-muted text-muted-foreground" },
};

const SPY_ICONS: Record<SpyMode, typeof Ear> = { listen: Ear, whisper: Mic, barge: Headphones };

/** The AI's card, in one line: what the customer wants, and their mood. */
function HandoffLine({ card }: { card: HandoffCard }) {
    const mood = card.sentiment ? SENTIMENT_LABELS[card.sentiment] : null;
    return (
        <span
            className="mt-1 flex items-start gap-1.5 text-xs text-violet-200"
            title={[card.summary, card.next_step && `À faire : ${card.next_step}`].filter(Boolean).join("\n")}
            data-testid="handoff-line"
        >
            <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet-300" />
            <span>
                {card.reason || "Transféré par l'agent IA"}
                {mood && <span className={`ml-1 ${mood.className}`}>· {mood.label}</span>}
            </span>
        </span>
    );
}

function direction(call: PbxCall) {
    if (call.direction === "inbound") return "←";
    if (call.direction === "outbound") return "→";
    return "↔";
}

export function PbxSupervision({
    live,
    tick,
    extensions,
    supervisor,
    onSupervisorChange,
    onOpenSettings,
    onOpenAlerts,
    onChanged,
}: {
    live: PbxLive;
    /** Seconds since `live` was received, to keep clocks running. */
    tick: number;
    extensions: Extension[];
    supervisor: string | null;
    onSupervisorChange: (uuid: string) => void;
    onOpenSettings: () => void;
    onOpenAlerts?: () => void;
    onChanged: () => void;
}) {
    const [busy, setBusy] = useState<string | null>(null);
    const listening = live.listening;
    const allowedSupervisors = listening.supervisors.length
        ? extensions.filter((e) => listening.supervisors.includes(e.uuid))
        : extensions;
    const supervisorAllowed = Boolean(supervisor && allowedSupervisors.some((e) => e.uuid === supervisor));

    const spy = async (call: PbxCall, mode: SpyMode) => {
        if (!supervisor || !call.user_uuid) return;
        setBusy(`${call.call_id}:${mode}`);
        const response = await spyApiV1PbxSupervisionSpyPost({
            body: { supervisor_user_uuid: supervisor, target_user_uuid: call.user_uuid, mode },
        });
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Impossible de lancer l'écoute"));
            return;
        }
        toast.success(
            `${SPY_LABELS[mode]} ${call.user_name ?? ""} : votre téléphone sonne, décrochez. Vous écoutez dès que vous répondez.`,
        );
    };

    const agentAction = async (agent: PbxLiveAgent, action: "pause" | "unpause") => {
        setBusy(`agent:${agent.id}`);
        const response = await agentActionApiV1PbxAgentsAgentNumberActionPost({
            path: { agent_number: agent.number, action },
            body: action === "pause" ? { reason: "Pause demandée par la supervision" } : {},
        });
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Action impossible"));
            return;
        }
        onChanged();
    };

    const spyButtons = (call: PbxCall | null) => {
        if (!call || !call.spyable || call.user_uuid === supervisor || !supervisorAllowed) {
            return <span className="text-xs text-muted-foreground">—</span>;
        }
        return (
            <span className="inline-flex flex-wrap justify-end gap-1">
                {listening.modes.map((mode) => {
                    const Icon = SPY_ICONS[mode];
                    return (
                        <Button
                            key={mode}
                            size="sm"
                            variant="outline"
                            disabled={busy !== null}
                            onClick={() => spy(call, mode)}
                            aria-label={`${SPY_LABELS[mode]} ${call.user_name ?? ""}`}
                        >
                            <Icon className="mr-1 h-3.5 w-3.5" />
                            {SPY_LABELS[mode]}
                        </Button>
                    );
                })}
            </span>
        );
    };

    const errors = Object.values(live.errors ?? {});
    const nonAgentCalls = live.calls.filter((c) => !live.agents.some((a) => a.call?.call_id === c.call_id));

    return (
        <div data-testid="pbx-supervision">
            <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-border/60 bg-card/40 p-4">
                <div className="min-w-64 space-y-1">
                    <Label htmlFor="supervisor-extension" className="text-xs text-muted-foreground">
                        Votre poste (il sonne quand vous écoutez un appel)
                    </Label>
                    <Select value={supervisor ?? undefined} onValueChange={onSupervisorChange}>
                        <SelectTrigger id="supervisor-extension" aria-label="Votre poste" className="w-72">
                            <SelectValue placeholder="Choisir votre poste" />
                        </SelectTrigger>
                        <SelectContent>
                            {allowedSupervisors.map((e) => (
                                <SelectItem key={e.uuid} value={e.uuid}>
                                    {e.extension ? `${e.extension} · ` : ""}
                                    {e.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="flex-1 text-sm text-muted-foreground">
                    {listening.enabled ? (
                        <>
                            Écoute activée : {listening.modes.map((m) => SPY_LABELS[m].toLowerCase()).join(", ")}.
                            {" "}Chaque écoute est inscrite au journal.
                        </>
                    ) : (
                        <span className="flex items-center gap-2">
                            <ShieldAlert className="h-4 w-4 text-amber-400" />
                            L&apos;écoute des appels est désactivée pour l&apos;entreprise.
                        </span>
                    )}
                </div>
                <span className="flex flex-wrap gap-2">
                    {onOpenAlerts && (
                        <Button variant="outline" onClick={onOpenAlerts}>
                            <BellRing className="mr-2 h-4 w-4" />
                            Alertes
                        </Button>
                    )}
                    <Button variant="outline" onClick={onOpenSettings}>
                        <Settings2 className="mr-2 h-4 w-4" />
                        Réglages de l&apos;écoute
                    </Button>
                </span>
            </div>

            {errors.length > 0 && (
                <div
                    className="mb-6 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm"
                    data-testid="pbx-supervision-errors"
                >
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                    <span>
                        Une partie de l&apos;état du PBX n&apos;a pas pu être lue
                        {live.errors.waiting ? " (appelants en attente : action QueueStatus refusée ?)" : ""} :{" "}
                        {errors[0]}
                    </span>
                </div>
            )}

            <PageSection
                title="Files du PBX"
                description="Appelants en attente d'un conseiller, en direct. En rouge : attente au-delà du seuil de qualité de service."
            >
                {live.queues.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucune file sur le PBX.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>File</TableHead>
                                <TableHead className="text-right">En attente</TableHead>
                                <TableHead className="text-right">Plus longue attente</TableHead>
                                <TableHead className="text-right">Disponibles</TableHead>
                                <TableHead className="text-right">En appel</TableHead>
                                <TableHead className="text-right">En pause</TableHead>
                                <TableHead>Appelants</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {live.queues.map((q) => {
                                const longest = q.waiting ? q.longest_wait_seconds + tick : 0;
                                const late = q.waiting > 0 && longest > q.sla_seconds;
                                return (
                                    <TableRow key={q.id} data-testid="pbx-live-queue">
                                        <TableCell>
                                            <span className="font-medium">{q.name}</span>
                                            {q.number && (
                                                <span className="ml-2 font-mono text-xs text-muted-foreground">{q.number}</span>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">{q.live ? q.waiting : "?"}</TableCell>
                                        <TableCell
                                            className={`text-right font-mono tabular-nums ${late ? "font-semibold text-red-400" : ""}`}
                                        >
                                            {q.waiting ? formatDuration(longest) : "—"}
                                        </TableCell>
                                        <TableCell
                                            className={`text-right tabular-nums ${q.waiting && !q.agents_available ? "text-red-400" : ""}`}
                                        >
                                            {q.agents_available}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">{q.agents_on_call}</TableCell>
                                        <TableCell className="text-right tabular-nums">{q.agents_paused}</TableCell>
                                        <TableCell>
                                            <span className="flex flex-wrap gap-1">
                                                {q.callers.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
                                                {q.callers.map((c) => (
                                                    <Badge
                                                        key={`${q.id}-${c.position}`}
                                                        variant="outline"
                                                        className={`${c.wait_seconds + tick > q.sla_seconds ? "border-red-500/50 text-red-300" : ""} ${c.handoff ? "border-violet-500/50" : ""}`}
                                                        title={
                                                            c.handoff
                                                                ? `Transféré par l'agent IA : ${c.handoff.reason ?? ""}${c.handoff.summary ? `\n${c.handoff.summary}` : ""}`
                                                                : undefined
                                                        }
                                                    >
                                                        {c.handoff && <Bot className="mr-1 h-3 w-3 text-violet-300" aria-label="Transféré par l'IA" />}
                                                        {c.position}. {c.name || c.handoff?.customer_name || c.number || "Numéro masqué"} ·{" "}
                                                        {formatDuration(c.wait_seconds + tick)}
                                                    </Badge>
                                                ))}
                                            </span>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <PageSection
                title="Conseillers du PBX"
                description="État de chaque agent, appel en cours, et supervision : écouter, chuchoter au conseiller (le client ne vous entend pas) ou intervenir."
            >
                {live.agents.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucun agent sur le PBX.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Conseiller</TableHead>
                                <TableHead>Statut</TableHead>
                                <TableHead>Appel en cours</TableHead>
                                <TableHead className="text-right">Supervision</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {live.agents.map((a) => {
                                const state = AGENT_STATE[a.state] ?? AGENT_STATE.logged_out;
                                return (
                                    <TableRow key={a.id} data-testid="pbx-live-agent">
                                        <TableCell>
                                            <span className="font-medium">{a.name}</span>
                                            <span className="ml-2 font-mono text-xs text-muted-foreground">{a.extension}</span>
                                        </TableCell>
                                        <TableCell>
                                            <span className="flex flex-wrap items-center gap-2">
                                                <Badge variant="outline" className={state.className}>
                                                    {state.label}
                                                </Badge>
                                                {a.paused_reason && (
                                                    <span className="text-xs text-muted-foreground">{a.paused_reason}</span>
                                                )}
                                                {a.state === "available" && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        disabled={busy !== null}
                                                        onClick={() => agentAction(a, "pause")}
                                                        aria-label={`Mettre ${a.name} en pause`}
                                                    >
                                                        <Pause className="h-3.5 w-3.5" />
                                                    </Button>
                                                )}
                                                {a.state === "paused" && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        disabled={busy !== null}
                                                        onClick={() => agentAction(a, "unpause")}
                                                        aria-label={`Reprendre ${a.name}`}
                                                    >
                                                        <Play className="h-3.5 w-3.5" />
                                                    </Button>
                                                )}
                                            </span>
                                        </TableCell>
                                        <TableCell className="text-sm">
                                            {a.call ? (
                                                <>
                                                    <span className="flex items-center gap-2">
                                                        <PhoneCall className="h-3.5 w-3.5 text-cyan-400" />
                                                        {direction(a.call)} {a.call.with_name || a.call.with_number || "Appel"}
                                                        <span className="font-mono text-xs tabular-nums text-muted-foreground">
                                                            {formatDuration(a.call.seconds + tick)}
                                                        </span>
                                                        {a.call.on_hold && <Badge variant="outline">En attente</Badge>}
                                                    </span>
                                                    {a.call.handoff && <HandoffLine card={a.call.handoff} />}
                                                </>
                                            ) : (
                                                <span className="text-muted-foreground">—</span>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right">{spyButtons(a.call)}</TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            {nonAgentCalls.length > 0 && (
                <PageSection
                    title="Autres conversations sur les postes"
                    description="Appels des postes qui ne sont pas des agents de file (accueil, direction, commerciaux…)."
                >
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Poste</TableHead>
                                <TableHead>Avec</TableHead>
                                <TableHead className="text-right">Durée</TableHead>
                                <TableHead className="text-right">Supervision</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {nonAgentCalls.map((c) => (
                                <TableRow key={c.call_id} data-testid="pbx-live-call">
                                    <TableCell>
                                        <span className="font-medium">{c.user_name || "Poste"}</span>
                                        <span className="ml-2 font-mono text-xs text-muted-foreground">{c.extension}</span>
                                    </TableCell>
                                    <TableCell>
                                        {direction(c)} {c.with_name || c.with_number || "—"}
                                        {c.state === "ringing" && (
                                            <Badge variant="outline" className="ml-2">
                                                Sonne
                                            </Badge>
                                        )}
                                        {c.handoff && <HandoffLine card={c.handoff} />}
                                    </TableCell>
                                    <TableCell className="text-right font-mono tabular-nums">
                                        {formatDuration(c.seconds + tick)}
                                    </TableCell>
                                    <TableCell className="text-right">{spyButtons(c)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </PageSection>
            )}

            {!supervisor && listening.enabled && (
                <p className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
                    <Users className="h-4 w-4" />
                    Choisissez votre poste ci-dessus pour écouter les appels.
                </p>
            )}
        </div>
    );
}

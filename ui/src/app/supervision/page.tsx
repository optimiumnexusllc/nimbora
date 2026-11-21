"use client";

import {
    AlertTriangle,
    Bot,
    CalendarClock,
    Ear,
    Headset,
    Hourglass,
    MessageSquareQuote,
    PhoneCall,
    Radio,
    UserCheck,
    Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { readSettingsApiV1PbxSupervisionSettingsGet, spyApiV1SupervisionSpyPost } from "@/client/sdk.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { formatDuration } from "@/components/supervision/format";
import { ListeningSettingsDialog } from "@/components/supervision/ListeningSettingsDialog";
import { LiveCallPanel,type LiveCallSummary } from "@/components/supervision/LiveCallPanel";
import { type Extension,PbxSupervision } from "@/components/supervision/PbxSupervision";
import { QueueStatistics } from "@/components/supervision/QueueStatistics";
import type { ListeningSettings } from "@/components/supervision/types";
import { useSupervisionStream } from "@/components/supervision/useSupervisionStream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

type AiCall = {
    run_id: number;
    agent_name?: string;
    caller?: string;
    direction?: string;
    state?: string;
    language?: string;
    node?: string;
    last_caller_text?: string;
    last_agent_text?: string;
    duration_seconds?: number;
    turns?: number;
};

type AgentRow = {
    id: number;
    display_name: string;
    extension: string;
    status: string;
    presence_reason?: string | null;
    is_supervisor?: boolean;
    call?: { with_number: string; with_name: string; seconds: number } | null;
};

type QueueRow = {
    slug: string;
    name: string;
    waiting: number;
    longest_wait_seconds: number;
    max_wait_seconds: number;
    in_conversation: number;
    available_agents: number;
};

const STATUS: Record<string, { label: string; className: string }> = {
    available: { label: "Disponible", className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" },
    on_call: { label: "En appel", className: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" },
    ringing: { label: "Sonne", className: "bg-violet-500/15 text-violet-300 border-violet-500/30" },
    paused: { label: "En pause", className: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
    offline: { label: "Hors ligne", className: "bg-muted text-muted-foreground" },
    disabled: { label: "Désactivé", className: "bg-muted text-muted-foreground" },
};

const CALL_STATE: Record<string, string> = {
    caller_speaking: "Le client parle",
    agent_speaking: "L'agent parle",
    listening: "Écoute",
    starting: "Connexion…",
};

function Kpi({
    icon: Icon,
    label,
    value,
    hint,
    alert,
}: {
    icon: typeof Bot;
    label: string;
    value: string | number;
    hint?: string;
    alert?: boolean;
}) {
    return (
        <div
            className={`card-weave rounded-xl border p-4 ${alert ? "border-amber-500/50" : "border-border/60"}`}
            data-testid={`kpi-${label}`}
        >
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Icon className={`h-4 w-4 ${alert ? "text-amber-400" : "text-cyan-400"}`} />
                {label}
            </div>
            <div className="mt-2 font-display text-3xl font-semibold tabular-nums">{value}</div>
            {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
        </div>
    );
}

const SUPERVISOR_KEY = "nimbora-supervisor-extension";

function readStoredSupervisor(): string | null {
    try {
        return window.localStorage.getItem(SUPERVISOR_KEY);
    } catch {
        return null;
    }
}

export default function SupervisionPage() {
    const { user, loading: authLoading, getAccessToken } = useAuth();
    const [selected, setSelected] = useState<LiveCallSummary | null>(null);
    const [tick, setTick] = useState(0);
    const [pbxTick, setPbxTick] = useState(0);
    const [settings, setSettings] = useState<(ListeningSettings & { extensions?: Extension[] }) | null>(null);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [supervisor, setSupervisor] = useState<string | null>(null);
    const settingsLoaded = useRef(false);
    const { ai: snapshot, pbx, mode, receivedAt, refresh } = useSupervisionStream({
        enabled: !authLoading && Boolean(user),
        getAccessToken: async () => (getAccessToken ? await getAccessToken() : null),
    });

    // Clocks keep running between two updates, each from its own side's.
    useEffect(() => {
        const since = (at: number) => (at ? Math.floor((Date.now() - at) / 1000) : 0);
        const update = () => {
            setTick(since(receivedAt.ai));
            setPbxTick(since(receivedAt.pbx));
        };
        update();
        const clock = window.setInterval(update, 1000);
        return () => window.clearInterval(clock);
    }, [receivedAt]);

    const pbxReady = Boolean(pbx && !pbx.unavailable);
    useEffect(() => {
        if (!pbxReady || settingsLoaded.current) return;
        settingsLoaded.current = true;
        void (async () => {
            const response = await readSettingsApiV1PbxSupervisionSettingsGet();
            if (response.error || !response.data) return;
            const loaded = response.data as unknown as ListeningSettings & { extensions?: Extension[] };
            setSettings(loaded);
            const stored = readStoredSupervisor();
            const known = (loaded.extensions ?? []).some((e) => e.uuid === stored);
            setSupervisor(known ? stored : (loaded.my_extension ?? null));
        })();
    }, [pbxReady]);

    const chooseSupervisor = (uuid: string) => {
        setSupervisor(uuid);
        try {
            window.localStorage.setItem(SUPERVISOR_KEY, uuid);
        } catch {
            // private mode: the choice lasts for this visit
        }
    };

    const spy = async (agentId: number, mode: "listen" | "whisper" | "barge") => {
        const response = await spyApiV1SupervisionSpyPost({ body: { agent_id: agentId, mode } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Impossible de lancer la supervision"));
            return;
        }
        toast.success("Votre softphone sonne : décrochez. Touches 4 / 5 / 6 : écouter / chuchoter / intervenir.");
    };

    if (!snapshot) {
        return (
            <PageLayout title="Supervision">
                <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
                    {Array.from({ length: 6 }).map((_, i) => (
                        <Skeleton key={i} className="h-28" />
                    ))}
                </div>
            </PageLayout>
        );
    }

    const k = snapshot.kpis;
    const aiCalls = snapshot.ai_calls as AiCall[];
    const agents = snapshot.agents as AgentRow[];
    const queues = snapshot.queues as QueueRow[];
    const canSpy = Boolean(snapshot.my_seat?.is_supervisor);
    const live = pbx && !pbx.unavailable ? pbx : null;
    const p = live?.kpis;
    // One picture: the built-in contact center and the enterprise PBX together.
    const waiting = (k.waiting ?? 0) + (p?.waiting ?? 0);
    const longest = Math.max(
        k.waiting ? (k.longest_wait_seconds ?? 0) + tick : 0,
        p?.waiting ? p.longest_wait_seconds + pbxTick : 0,
    );
    const humanCalls = (k.human_calls ?? 0) + (p?.calls ?? 0);
    const available = (k.agents_available ?? 0) + (p?.agents_available ?? 0);
    const onCall = (k.agents_on_call ?? 0) + (p?.agents_on_call ?? 0);
    const paused = (k.agents_paused ?? 0) + (p?.agents_paused ?? 0);

    return (
        <PageLayout
            title="Supervision"
            description="Tout ce qui se passe maintenant : appels IA, files d'attente et conseillers. Intervenez en un clic."
            actions={
                <span className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="stream-mode">
                    <Radio
                        className={`h-4 w-4 ${mode === "live" ? "animate-pulse text-emerald-400" : "text-amber-400"}`}
                    />
                    {mode === "live"
                        ? "En direct · temps réel"
                        : mode === "polling"
                          ? "Actualisé toutes les 5 s"
                          : "Connexion au direct…"}
                </span>
            }
        >
            {snapshot.contact_center_enabled && snapshot.telephony !== "ok" && (
                <div className="mb-6 flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
                    <AlertTriangle className="h-4 w-4 text-amber-400" />
                    {snapshot.telephony === "unreachable"
                        ? "Le serveur téléphonique (Asterisk) ne répond pas : l'état des conseillers n'est pas à jour."
                        : "La téléphonie de la plateforme n'est pas configurée : seuls les appels IA sont suivis."}
                </div>
            )}

            <div className="mb-8 grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
                <Kpi icon={Bot} label="Appels IA" value={k.ai_calls ?? 0} hint="en cours" />
                <Kpi icon={Headset} label="Appels conseillers" value={humanCalls} hint="en cours" />
                <Kpi
                    icon={Hourglass}
                    label="En attente"
                    value={waiting}
                    hint={waiting && longest ? `plus longue : ${formatDuration(longest)}` : "personne n'attend"}
                    alert={waiting > 0 && longest > 60}
                />
                <Kpi icon={UserCheck} label="Disponibles" value={available} hint="conseillers" />
                <Kpi
                    icon={Users}
                    label="Occupés / pause"
                    value={`${onCall} / ${paused}`}
                    hint="en appel / en pause"
                />
                <Kpi icon={CalendarClock} label="Rappels" value={k.callbacks_pending ?? 0} hint="à faire" />
            </div>

            <PageSection
                title="Appels IA en direct"
                description="Ouvrez un appel pour suivre la conversation mot à mot, souffler une consigne à l'IA ou reprendre la main."
            >
                {aiCalls.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucun appel IA en cours.</p>
                ) : (
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {aiCalls.map((call) => (
                            <button
                                key={call.run_id}
                                type="button"
                                data-testid="ai-call-card"
                                onClick={() => setSelected(call)}
                                className="group rounded-xl border border-border/60 bg-card/40 p-4 text-left transition hover:border-primary/60 hover:bg-primary/5"
                            >
                                <div className="flex items-center gap-2">
                                    <span
                                        className={`h-2 w-2 rounded-full ${
                                            call.state === "caller_speaking"
                                                ? "animate-pulse bg-cyan-400"
                                                : call.state === "agent_speaking"
                                                  ? "animate-pulse bg-violet-400"
                                                  : "bg-emerald-400"
                                        }`}
                                    />
                                    <span className="font-medium">{call.agent_name}</span>
                                    {call.language && <Badge variant="outline">{call.language.toUpperCase()}</Badge>}
                                    <span className="ml-auto font-mono text-sm tabular-nums text-muted-foreground">
                                        {formatDuration((call.duration_seconds ?? 0) + tick)}
                                    </span>
                                </div>
                                <div className="mt-1 text-xs text-muted-foreground">
                                    {call.direction === "outbound" ? "→ " : "← "}
                                    {call.caller || "numéro masqué"} · {CALL_STATE[call.state ?? ""] ?? "En ligne"}
                                    {call.node ? ` · ${call.node}` : ""}
                                </div>
                                {call.last_caller_text && (
                                    <p className="mt-3 line-clamp-2 text-sm">
                                        <span className="text-cyan-300">Client : </span>
                                        {call.last_caller_text}
                                    </p>
                                )}
                                {call.last_agent_text && (
                                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                                        <span className="text-violet-300">Agent : </span>
                                        {call.last_agent_text}
                                    </p>
                                )}
                                <span className="mt-3 flex items-center gap-1 text-xs text-primary opacity-0 transition group-hover:opacity-100">
                                    <MessageSquareQuote className="h-3.5 w-3.5" />
                                    Suivre et intervenir
                                </span>
                            </button>
                        ))}
                    </div>
                )}
            </PageSection>

            {pbx?.unavailable && (
                <div className="mb-6 flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
                    <AlertTriangle className="h-4 w-4 text-amber-400" />
                    Le PBX de l&apos;entreprise ne répond pas : {pbx.unavailable}
                </div>
            )}

            {live && (
                <PbxSupervision
                    live={live}
                    tick={pbxTick}
                    extensions={settings?.extensions ?? []}
                    supervisor={supervisor}
                    onSupervisorChange={chooseSupervisor}
                    onOpenSettings={() => setSettingsOpen(true)}
                    onChanged={refresh}
                />
            )}

            {snapshot.contact_center_enabled && (
                <>
                    <PageSection title="Files d'attente" description="Clients en attente d'un conseiller, file par file.">
                        {queues.length === 0 ? (
                            <p className="text-sm text-muted-foreground">Aucune file configurée.</p>
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>File</TableHead>
                                        <TableHead className="text-right">En attente</TableHead>
                                        <TableHead className="text-right">Plus longue attente</TableHead>
                                        <TableHead className="text-right">En conversation</TableHead>
                                        <TableHead className="text-right">Conseillers disponibles</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {queues.map((q) => {
                                        const late = q.waiting > 0 && q.longest_wait_seconds > q.max_wait_seconds * 0.75;
                                        return (
                                            <TableRow key={q.slug}>
                                                <TableCell className="font-medium">{q.name}</TableCell>
                                                <TableCell className="text-right tabular-nums">{q.waiting}</TableCell>
                                                <TableCell
                                                    className={`text-right font-mono tabular-nums ${late ? "text-amber-400" : ""}`}
                                                >
                                                    {q.waiting ? formatDuration(q.longest_wait_seconds + tick) : "—"}
                                                </TableCell>
                                                <TableCell className="text-right tabular-nums">{q.in_conversation}</TableCell>
                                                <TableCell
                                                    className={`text-right tabular-nums ${
                                                        q.waiting && !q.available_agents ? "text-red-400" : ""
                                                    }`}
                                                >
                                                    {q.available_agents}
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        )}
                    </PageSection>

                    <PageSection
                        title="Conseillers"
                        description={
                            canSpy
                                ? "Écoutez, chuchotez au conseiller (le client ne vous entend pas) ou intervenez dans l'appel : votre softphone sonne."
                                : "L'écoute et le chuchotement sont réservés aux postes superviseurs (Centre d'appels → Postes)."
                        }
                    >
                        {agents.length === 0 ? (
                            <p className="text-sm text-muted-foreground">Aucun poste de conseiller.</p>
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
                                    {agents.map((a) => {
                                        const status = STATUS[a.status] ?? STATUS.offline;
                                        return (
                                            <TableRow key={a.id} data-testid="agent-row">
                                                <TableCell>
                                                    <span className="font-medium">{a.display_name}</span>
                                                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                                                        {a.extension}
                                                    </span>
                                                    {a.is_supervisor && (
                                                        <Badge variant="outline" className="ml-2">
                                                            Superviseur
                                                        </Badge>
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    <Badge variant="outline" className={status.className}>
                                                        {status.label}
                                                    </Badge>
                                                    {a.status === "paused" && a.presence_reason && (
                                                        <span className="ml-2 text-xs text-muted-foreground">
                                                            {a.presence_reason}
                                                        </span>
                                                    )}
                                                </TableCell>
                                                <TableCell className="text-sm">
                                                    {a.call ? (
                                                        <span className="flex items-center gap-2">
                                                            <PhoneCall className="h-3.5 w-3.5 text-cyan-400" />
                                                            {a.call.with_name || a.call.with_number || "Appel"}
                                                            <span className="font-mono text-xs tabular-nums text-muted-foreground">
                                                                {formatDuration(a.call.seconds + tick)}
                                                            </span>
                                                        </span>
                                                    ) : (
                                                        <span className="text-muted-foreground">—</span>
                                                    )}
                                                </TableCell>
                                                <TableCell className="text-right">
                                                    {a.status === "on_call" && canSpy ? (
                                                        <span className="inline-flex gap-1">
                                                            <Button size="sm" variant="outline" onClick={() => spy(a.id, "listen")}>
                                                                <Ear className="mr-1 h-3.5 w-3.5" />
                                                                Écouter
                                                            </Button>
                                                            <Button size="sm" variant="outline" onClick={() => spy(a.id, "whisper")}>
                                                                Chuchoter
                                                            </Button>
                                                            <Button size="sm" variant="outline" onClick={() => spy(a.id, "barge")}>
                                                                Intervenir
                                                            </Button>
                                                        </span>
                                                    ) : (
                                                        <span className="text-xs text-muted-foreground">—</span>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        )}
                    </PageSection>
                </>
            )}

            {live && (
                <>
                    <QueueStatistics ready={Boolean(live)} />
                    <ListeningSettingsDialog
                        open={settingsOpen}
                        onOpenChange={setSettingsOpen}
                        settings={settings}
                        extensions={settings?.extensions ?? []}
                        onSaved={(saved) => {
                            setSettings((current) => ({ ...(current ?? {}), ...saved }));
                            refresh();
                        }}
                    />
                </>
            )}

            <LiveCallPanel
                call={selected}
                queues={[
                    ...queues.map((q) => ({ slug: q.slug, name: q.name })),
                    // The AI call can also be handed to a queue of the company PBX.
                    ...(live?.queues ?? []).map((q) => ({ slug: `pbx-queue:${q.id}`, name: `${q.name} (PBX)` })),
                ]}
                onClose={() => setSelected(null)}
            />
        </PageLayout>
    );
}

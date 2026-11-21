"use client";

import { Bot, Expand, Hourglass, PhoneCall, Siren, TriangleAlert, UserCheck, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { BrandLogo } from "@/components/BrandLogo";
import { formatDuration } from "@/components/supervision/format";
import type { PbxLive, PbxLiveQueue } from "@/components/supervision/types";
import { useSupervisionStream } from "@/components/supervision/useSupervisionStream";
import { useAuth } from "@/lib/auth";

function Clock() {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(new Date()), 1000);
        return () => window.clearInterval(timer);
    }, []);
    return (
        <div className="text-right">
            <div className="font-mono text-5xl font-semibold tabular-nums">
                {now.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            </div>
            <div className="text-lg text-slate-400">
                {now.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}
            </div>
        </div>
    );
}

function Big({
    icon: Icon,
    label,
    value,
    tone = "text-white",
    testId,
}: {
    icon: typeof Bot;
    label: string;
    value: string | number;
    tone?: string;
    testId: string;
}) {
    return (
        <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-6" data-testid={testId}>
            <div className="flex items-center gap-2 text-xl text-slate-400">
                <Icon className="h-6 w-6" />
                {label}
            </div>
            <div className={`mt-2 font-display text-7xl font-bold tabular-nums ${tone}`}>{value}</div>
        </div>
    );
}

function QueueTile({ queue, tick }: { queue: PbxLiveQueue; tick: number }) {
    const longest = queue.waiting ? queue.longest_wait_seconds + tick : 0;
    const late = queue.waiting > 0 && longest > queue.sla_seconds;
    const nobody = queue.waiting > 0 && queue.agents_available === 0;
    return (
        <div
            className={`rounded-3xl border p-6 ${
                late || nobody ? "border-red-500/60 bg-red-500/10" : "border-white/10 bg-white/[0.04]"
            }`}
            data-testid="wall-queue"
        >
            <div className="flex items-baseline justify-between gap-3">
                <h2 className="truncate text-3xl font-semibold">{queue.name}</h2>
                {queue.number && <span className="font-mono text-xl text-slate-500">{queue.number}</span>}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-4">
                <div>
                    <div className="text-lg text-slate-400">En attente</div>
                    <div className={`font-display text-6xl font-bold tabular-nums ${queue.waiting ? "text-amber-300" : ""}`}>
                        {queue.live ? queue.waiting : "?"}
                    </div>
                </div>
                <div>
                    <div className="text-lg text-slate-400">Plus longue</div>
                    <div className={`font-mono text-6xl font-bold tabular-nums ${late ? "text-red-400" : ""}`}>
                        {queue.waiting ? formatDuration(longest) : "—"}
                    </div>
                </div>
            </div>
            <div className="mt-4 flex gap-5 text-xl">
                <span className={queue.agents_available ? "text-emerald-300" : "text-red-300"}>
                    {queue.agents_available} disponible{queue.agents_available > 1 ? "s" : ""}
                </span>
                <span className="text-cyan-300">{queue.agents_on_call} en appel</span>
                <span className="text-amber-300">{queue.agents_paused} en pause</span>
            </div>
        </div>
    );
}

const AGENT_TONE: Record<string, string> = {
    available: "bg-emerald-500",
    on_call: "bg-cyan-500",
    ringing: "bg-violet-500 animate-pulse",
    paused: "bg-amber-500",
    logged_out: "bg-slate-600",
};

/**
 * The wall display: big, readable from across the room, real time. Open it on
 * a TV of the call center floor (full screen with the button or F11).
 */
export default function SupervisionWallPage() {
    const { user, loading, getAccessToken } = useAuth();
    const { ai, pbx, mode, receivedAt } = useSupervisionStream({
        enabled: !loading && Boolean(user),
        getAccessToken: async () => (getAccessToken ? await getAccessToken() : null),
    });
    const [tick, setTick] = useState(0);

    useEffect(() => {
        const update = () => setTick(receivedAt.pbx ? Math.floor((Date.now() - receivedAt.pbx) / 1000) : 0);
        update();
        const timer = window.setInterval(update, 1000);
        return () => window.clearInterval(timer);
    }, [receivedAt]);

    const live: PbxLive | null = pbx && !pbx.unavailable ? pbx : null;
    const k = live?.kpis;
    const aiCalls = ai?.ai_calls?.length ?? 0;
    const longest = live?.queues.some((q) => q.waiting)
        ? Math.max(...live.queues.filter((q) => q.waiting).map((q) => q.longest_wait_seconds)) + tick
        : 0;
    const alerts = live?.alerts ?? [];

    return (
        <div className="min-h-screen bg-[#05070f] p-8 text-white" data-testid="supervision-wall">
            <header className="mb-8 flex items-center justify-between gap-6">
                <div className="flex items-center gap-5">
                    <BrandLogo className="h-12" inverse />
                    <div className="text-2xl text-slate-400">
                        Supervision
                        <span className={`ml-3 inline-block h-3 w-3 rounded-full ${mode === "live" ? "animate-pulse bg-emerald-400" : "bg-amber-400"}`} />
                    </div>
                </div>
                <div className="flex items-center gap-6">
                    <button
                        type="button"
                        className="rounded-full border border-white/15 p-3 text-slate-300 hover:bg-white/10"
                        aria-label="Plein écran"
                        onClick={() => void document.documentElement.requestFullscreen?.()}
                    >
                        <Expand className="h-6 w-6" />
                    </button>
                    <Clock />
                </div>
            </header>

            {alerts.length > 0 && (
                <div className="mb-8 space-y-3" role="alert">
                    {alerts.map((alert) => (
                        <div
                            key={alert.key}
                            className={`flex items-center gap-4 rounded-2xl px-6 py-4 text-2xl font-semibold ${
                                alert.level === "critical" ? "bg-red-600/90" : "bg-amber-500/90 text-black"
                            }`}
                        >
                            {alert.level === "critical" ? (
                                <Siren className="h-8 w-8 animate-pulse" />
                            ) : (
                                <TriangleAlert className="h-8 w-8" />
                            )}
                            {alert.message}
                        </div>
                    ))}
                </div>
            )}

            <div className="mb-8 grid grid-cols-2 gap-6 lg:grid-cols-5">
                <Big icon={Hourglass} label="En attente" value={k?.waiting ?? 0} tone={k?.waiting ? "text-amber-300" : "text-white"} testId="wall-waiting" />
                <Big
                    icon={Hourglass}
                    label="Plus longue attente"
                    value={longest ? formatDuration(longest) : "—"}
                    tone={alerts.length ? "text-red-400" : "text-white"}
                    testId="wall-longest"
                />
                <Big icon={UserCheck} label="Disponibles" value={k?.agents_available ?? 0} tone="text-emerald-300" testId="wall-available" />
                <Big icon={PhoneCall} label="En appel" value={k?.agents_on_call ?? 0} tone="text-cyan-300" testId="wall-on-call" />
                <Big icon={Bot} label="Appels IA" value={aiCalls} tone="text-violet-300" testId="wall-ai" />
            </div>

            {live ? (
                <>
                    <div className="mb-8 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
                        {live.queues.map((queue) => (
                            <QueueTile key={queue.id} queue={queue} tick={tick} />
                        ))}
                    </div>
                    <div className="flex flex-wrap gap-3" aria-label="Conseillers">
                        {live.agents.map((agent) => (
                            <span
                                key={agent.id}
                                className="flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.04] px-5 py-2 text-xl"
                                data-testid="wall-agent"
                            >
                                <span className={`h-3.5 w-3.5 rounded-full ${AGENT_TONE[agent.state] ?? "bg-slate-600"}`} />
                                {agent.name}
                                {agent.call && (
                                    <span className="font-mono text-base text-slate-400">
                                        {formatDuration(agent.call.seconds + tick)}
                                    </span>
                                )}
                            </span>
                        ))}
                    </div>
                </>
            ) : (
                <p className="flex items-center gap-3 text-2xl text-slate-400">
                    <Users className="h-7 w-7" />
                    {pbx === undefined ? "Connexion…" : pbx?.unavailable ? `PBX injoignable : ${pbx.unavailable}` : "Aucun PBX connecté."}
                </p>
            )}
        </div>
    );
}

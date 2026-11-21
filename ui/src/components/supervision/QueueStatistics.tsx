"use client";

import { BarChart3, Info } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { readStatisticsApiV1PbxSupervisionStatisticsGet } from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { ChoiceChips } from "@/components/ui/choice-chips";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";

import { formatDuration } from "./format";

type Period = "today" | "yesterday" | "7d" | "30d";

type QueueStat = {
    queue_id: number;
    name: string;
    received: number;
    answered: number;
    abandoned: number;
    unanswered: number;
    closed: number;
    average_wait_seconds: number;
    answered_rate: number | null;
    service_level: number | null;
};

type AgentStat = {
    agent_id: number;
    name: string;
    number: string;
    answered: number;
    conversation_seconds: number;
    average_talk_seconds: number;
    login_seconds: number;
    pause_seconds: number;
    occupancy: number | null;
};

type Statistics = {
    period: Period;
    sla_seconds: number;
    timezone: string;
    queues: QueueStat[];
    agents: AgentStat[];
    totals: {
        received: number;
        answered: number;
        abandoned: number;
        answered_rate: number | null;
        service_level: number | null;
        average_wait_seconds: number;
    };
};

const PERIODS: { value: Period; label: string }[] = [
    { value: "today", label: "Aujourd'hui" },
    { value: "yesterday", label: "Hier" },
    { value: "7d", label: "7 jours" },
    { value: "30d", label: "30 jours" },
];

function percent(value: number | null | undefined) {
    return value === null || value === undefined ? "—" : `${Math.round(value)} %`;
}

function hours(seconds: number) {
    if (!seconds) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
}

function Gauge({ label, value, good }: { label: string; value: number | null; good: number }) {
    const tone =
        value === null ? "text-muted-foreground" : value >= good ? "text-emerald-300" : value >= good - 15 ? "text-amber-300" : "text-red-300";
    return (
        <div className="rounded-xl border border-border/60 p-4" data-testid={`stat-${label}`}>
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className={`mt-1 font-display text-3xl font-semibold tabular-nums ${tone}`}>{percent(value)}</div>
        </div>
    );
}

export function QueueStatistics({ ready }: { ready: boolean }) {
    const [period, setPeriod] = useState<Period>("today");
    const [stats, setStats] = useState<Statistics | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async (wanted: Period) => {
        setStats(null);
        setError(null);
        const response = await readStatisticsApiV1PbxSupervisionStatisticsGet({ query: { period: wanted } });
        if (response.error) {
            setError(detailFromError(response.error, "Statistiques indisponibles"));
            return;
        }
        setStats(response.data as unknown as Statistics);
    }, []);

    useEffect(() => {
        if (ready) void load(period);
    }, [ready, period, load]);

    return (
        <PageSection
            title="Statistiques des files et des conseillers"
            description="Taux de décroché, attente, niveau de service et activité de chaque conseiller."
            actions={
                <ChoiceChips
                    options={PERIODS}
                    value={period}
                    onChange={(value) => setPeriod(value as Period)}
                    className="p-0"
                />
            }
        >
            {error && <p className="text-sm text-amber-300">{error}</p>}
            {!error && !stats && <Skeleton className="h-40" />}
            {stats && (
                <div className="space-y-6" data-testid="queue-statistics">
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                        <div className="rounded-xl border border-border/60 p-4">
                            <div className="text-xs text-muted-foreground">Appels reçus</div>
                            <div className="mt-1 font-display text-3xl font-semibold tabular-nums">{stats.totals.received}</div>
                            <div className="text-xs text-muted-foreground">
                                {stats.totals.answered} décrochés · {stats.totals.abandoned} abandonnés
                            </div>
                        </div>
                        <Gauge label="Taux de décroché" value={stats.totals.answered_rate} good={90} />
                        <Gauge label={`Niveau de service (< ${stats.sla_seconds} s)`} value={stats.totals.service_level} good={80} />
                        <div className="rounded-xl border border-border/60 p-4">
                            <div className="text-xs text-muted-foreground">Attente moyenne</div>
                            <div className="mt-1 font-display text-3xl font-semibold tabular-nums">
                                {formatDuration(stats.totals.average_wait_seconds)}
                            </div>
                        </div>
                        <div className="rounded-xl border border-border/60 p-4">
                            <div className="text-xs text-muted-foreground">Conseillers actifs</div>
                            <div className="mt-1 font-display text-3xl font-semibold tabular-nums">
                                {stats.agents.filter((a) => a.login_seconds > 0).length}
                            </div>
                        </div>
                    </div>

                    {stats.queues.length > 0 && (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>File</TableHead>
                                    <TableHead className="text-right">Reçus</TableHead>
                                    <TableHead className="text-right">Décrochés</TableHead>
                                    <TableHead className="text-right">Abandonnés</TableHead>
                                    <TableHead className="text-right">Sans réponse</TableHead>
                                    <TableHead className="text-right">Taux de décroché</TableHead>
                                    <TableHead className="text-right">Niveau de service</TableHead>
                                    <TableHead className="text-right">Attente moyenne</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {stats.queues.map((q) => (
                                    <TableRow key={q.queue_id} data-testid="queue-stat">
                                        <TableCell className="font-medium">{q.name}</TableCell>
                                        <TableCell className="text-right tabular-nums">{q.received}</TableCell>
                                        <TableCell className="text-right tabular-nums">{q.answered}</TableCell>
                                        <TableCell className="text-right tabular-nums">{q.abandoned}</TableCell>
                                        <TableCell className="text-right tabular-nums">{q.unanswered + q.closed}</TableCell>
                                        <TableCell className="text-right tabular-nums">{percent(q.answered_rate)}</TableCell>
                                        <TableCell className="text-right tabular-nums">{percent(q.service_level)}</TableCell>
                                        <TableCell className="text-right font-mono tabular-nums">
                                            {formatDuration(q.average_wait_seconds)}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}

                    {stats.agents.length > 0 && (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Conseiller</TableHead>
                                    <TableHead className="text-right">Appels décrochés</TableHead>
                                    <TableHead className="text-right">Durée moyenne</TableHead>
                                    <TableHead className="text-right">En conversation</TableHead>
                                    <TableHead className="text-right">Connecté</TableHead>
                                    <TableHead className="text-right">En pause</TableHead>
                                    <TableHead className="text-right">Occupation</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {stats.agents.map((a) => (
                                    <TableRow key={a.agent_id} data-testid="agent-stat">
                                        <TableCell>
                                            <span className="font-medium">{a.name}</span>
                                            <span className="ml-2 font-mono text-xs text-muted-foreground">{a.number}</span>
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">{a.answered}</TableCell>
                                        <TableCell className="text-right font-mono tabular-nums">
                                            {a.answered ? formatDuration(a.average_talk_seconds) : "—"}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">{hours(a.conversation_seconds)}</TableCell>
                                        <TableCell className="text-right tabular-nums">{hours(a.login_seconds)}</TableCell>
                                        <TableCell className="text-right tabular-nums">{hours(a.pause_seconds)}</TableCell>
                                        <TableCell className="text-right tabular-nums">{percent(a.occupancy)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}

                    {stats.queues.length === 0 && stats.agents.length === 0 && (
                        <p className="flex items-center gap-2 text-sm text-muted-foreground">
                            <BarChart3 className="h-4 w-4" />
                            Aucun appel de file sur la période.
                        </p>
                    )}
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Info className="h-3.5 w-3.5" />
                        Calculées par le PBX toutes les 6 heures (fuseau {stats.timezone}) : les appels des dernières heures
                        peuvent ne pas encore y figurer. Le direct est dans les tableaux ci-dessus.
                    </p>
                </div>
            )}
        </PageSection>
    );
}

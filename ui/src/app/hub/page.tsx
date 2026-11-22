"use client";

import { ArrowDownRight, ArrowUpRight, CalendarCheck, Headphones, MessagesSquare, Phone, Table2, Target, UserPlus } from "lucide-react";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { readBusinessHubApiV1BusinessHubGet } from "@/client/sdk.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { changeText, formatNumber, type Hub, type Kpi, SERIES, shortDay } from "@/lib/businessHub";
import { cn } from "@/lib/utils";

const PERIODS = [
    ["7d", "7 jours"],
    ["30d", "30 jours"],
    ["90d", "90 jours"],
] as const;

function Tile({ label, kpi, icon: Icon, detail }: { label: string; kpi: Kpi; icon: typeof Phone; detail?: string }) {
    const change = changeText(kpi);
    return (
        <Card data-testid="kpi">
            <CardContent className="space-y-1 p-4">
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Icon className="size-4" aria-hidden /> {label}
                </p>
                <p className="text-3xl font-semibold tabular-nums">{formatNumber(kpi.value)}</p>
                <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                    <span className={cn("inline-flex items-center gap-0.5 font-medium text-foreground")} title={`Période précédente : ${formatNumber(kpi.previous)}`}>
                        {change.tone === "up" && <ArrowUpRight className="size-3.5" aria-label="en hausse" />}
                        {change.tone === "down" && <ArrowDownRight className="size-3.5" aria-label="en baisse" />}
                        {change.text}
                    </span>
                    {detail && <span>{detail}</span>}
                </p>
            </CardContent>
        </Card>
    );
}

export default function BusinessHubPage() {
    const { user, loading: authLoading } = useAuth();
    const { resolvedTheme } = useTheme();
    const [period, setPeriod] = useState<Hub["period"]>("30d");
    const [hub, setHub] = useState<Hub | null>(null);
    const [asTable, setAsTable] = useState(false);

    const load = useCallback(async () => {
        const response = await readBusinessHubApiV1BusinessHubGet({ query: { period } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Tableau de bord indisponible"));
            return;
        }
        setHub(response.data as unknown as Hub);
    }, [period]);

    useEffect(() => {
        if (authLoading || !user) return;
        void load();
    }, [authLoading, user, load]);

    const dark = resolvedTheme !== "light";
    const k = hub?.kpis;
    return (
        <PageLayout
            title="AI Business Hub"
            description="Ce que vos agents IA et votre équipe ont fait : conversations par canal, appels, rendez-vous, prospects — comparé à la période précédente."
            width="full"
            actions={
                <div className="flex rounded-lg border border-border/60 p-0.5" role="group" aria-label="Période">
                    {PERIODS.map(([value, label]) => (
                        <Button key={value} size="sm" variant={period === value ? "secondary" : "ghost"} aria-pressed={period === value} onClick={() => setPeriod(value)}>
                            {label}
                        </Button>
                    ))}
                </div>
            }
        >
            {!hub || !k ? (
                <p className="py-12 text-center text-sm text-muted-foreground">Chargement…</p>
            ) : (
                <div className="space-y-6">
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                        <Tile label="Conversations" icon={MessagesSquare} kpi={k.conversations} />
                        <Tile label="Appels IA" icon={Phone} kpi={k.ai_calls} detail={`${k.ai_calls.inbound} entrants · ${k.ai_calls.outbound} sortants · ${formatNumber(k.ai_calls.minutes ?? 0)} min`} />
                        <Tile label="Appels humains" icon={Headphones} kpi={k.human_calls} detail={`${formatNumber(k.human_calls.minutes ?? 0)} min`} />
                        <Tile label="Rendez-vous pris" icon={CalendarCheck} kpi={k.appointments} detail={`${k.appointments.upcoming} à venir`} />
                        <Tile
                            label="Nouveaux prospects"
                            icon={Target}
                            kpi={k.leads}
                            detail={`${k.leads.qualified} qualifiés · ${k.leads.won} gagnés${k.leads.conversion !== null ? ` (${formatNumber(k.leads.conversion)} %)` : ""}`}
                        />
                        <Tile label="Nouveaux clients" icon={UserPlus} kpi={k.customers} />
                    </div>

                    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
                        <PageSection
                            title="Activité par jour"
                            description={`Conversations par canal (jours dans le fuseau ${hub.timezone}).`}
                            actions={
                                <Button variant="ghost" size="sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
                                    <Table2 /> {asTable ? "Graphique" : "Tableau"}
                                </Button>
                            }
                        >
                            {asTable ? (
                                <div className="max-h-80 overflow-y-auto">
                                    <Table data-testid="daily-table">
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>Jour</TableHead>
                                                {SERIES.map((s) => (
                                                    <TableHead key={s.key} className="text-right">
                                                        {s.label}
                                                    </TableHead>
                                                ))}
                                                <TableHead className="text-right">Rendez-vous</TableHead>
                                                <TableHead className="text-right">Prospects</TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {hub.daily.map((d) => (
                                                <TableRow key={d.day}>
                                                    <TableCell>{shortDay(d.day)}</TableCell>
                                                    {SERIES.map((s) => (
                                                        <TableCell key={s.key} className="text-right tabular-nums">
                                                            {d[s.key]}
                                                        </TableCell>
                                                    ))}
                                                    <TableCell className="text-right tabular-nums">{d.appointments}</TableCell>
                                                    <TableCell className="text-right tabular-nums">{d.leads}</TableCell>
                                                </TableRow>
                                            ))}
                                        </TableBody>
                                    </Table>
                                </div>
                            ) : (
                                <div className="h-72" data-testid="daily-chart">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <BarChart data={hub.daily} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                                            <CartesianGrid vertical={false} stroke="currentColor" strokeOpacity={0.08} />
                                            <XAxis dataKey="day" tickFormatter={shortDay} tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }} tickLine={false} axisLine={false} minTickGap={16} />
                                            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }} tickLine={false} axisLine={false} />
                                            <Tooltip
                                                cursor={{ fill: "currentColor", fillOpacity: 0.06 }}
                                                labelFormatter={(day) => shortDay(String(day))}
                                                contentStyle={{ background: dark ? "#1a1a19" : "#fcfcfb", border: "1px solid rgba(127,127,127,.3)", borderRadius: 8, fontSize: 12 }}
                                            />
                                            <Legend
                                                iconType="circle"
                                                itemSorter={(item) => SERIES.findIndex((s) => s.key === item.dataKey)}
                                                wrapperStyle={{ fontSize: 12 }}
                                                formatter={(label) => <span className="text-foreground">{label}</span>}
                                            />
                                            {SERIES.map((s, i) => (
                                                <Bar
                                                    key={s.key}
                                                    dataKey={s.key}
                                                    name={s.label}
                                                    stackId="channels"
                                                    fill={dark ? s.dark : s.light}
                                                    stroke={dark ? "#1a1a19" : "#fcfcfb"}
                                                    strokeWidth={1}
                                                    radius={i === SERIES.length - 1 ? [4, 4, 0, 0] : 0}
                                                    maxBarSize={28}
                                                />
                                            ))}
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            )}
                        </PageSection>

                        <PageSection title="Par canal" description="Part des conversations de la période.">
                            <ul className="space-y-3" data-testid="channels">
                                {hub.channels.map((c, i) => (
                                    <li key={c.channel} className="space-y-1 text-sm">
                                        <p className="flex justify-between">
                                            <span>{c.label}</span>
                                            <span className="tabular-nums">
                                                {formatNumber(c.count)} · {formatNumber(c.share)} %
                                            </span>
                                        </p>
                                        <div className="h-2 rounded-full bg-muted">
                                            <div
                                                className="h-2 rounded-full"
                                                style={{ width: `${c.share}%`, background: dark ? [SERIES[0].dark, SERIES[2].dark, SERIES[3].dark][i] : [SERIES[0].light, SERIES[2].light, SERIES[3].light][i] }}
                                            />
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </PageSection>
                    </div>

                    <div className="grid gap-6 lg:grid-cols-2">
                        <PageSection title="Ce que les agents ont fait">
                            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm" data-testid="actions">
                                {(
                                    [
                                        ["Passations à un humain", `${hub.actions.handoffs}${hub.actions.handoff_rate !== null ? ` (${formatNumber(hub.actions.handoff_rate as number)} % des appels IA)` : ""}`],
                                        ["… prises par un conseiller", hub.actions.handoffs_answered],
                                        ["Messages envoyés (SMS, WhatsApp, e-mail)", hub.actions.messages_sent],
                                        ["Messages WhatsApp échangés", hub.actions.whatsapp_messages],
                                        ["Tickets ouverts", `${hub.actions.tickets_created} (${hub.actions.tickets_open} en cours)`],
                                        ["Rappels planifiés / faits", `${hub.actions.callbacks_created} / ${hub.actions.callbacks_done}`],
                                    ] as const
                                ).map(([label, value]) => (
                                    <div key={label}>
                                        <dt className="text-muted-foreground">{label}</dt>
                                        <dd className="text-lg font-medium tabular-nums">{value}</dd>
                                    </div>
                                ))}
                            </dl>
                        </PageSection>
                        <PageSection title="Pipeline ouvert" description="Prospects en cours et leur budget maximum.">
                            {hub.pipeline.length === 0 ? (
                                <p className="text-sm text-muted-foreground">Aucun prospect en cours.</p>
                            ) : (
                                <ul className="space-y-2 text-sm" data-testid="pipeline-value">
                                    {hub.pipeline.map((p) => (
                                        <li key={p.currency} className="flex justify-between">
                                            <span>
                                                {p.open_leads} prospect{p.open_leads > 1 ? "s" : ""} en cours
                                            </span>
                                            <span className="text-lg font-medium tabular-nums">{p.text}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                            <a className="mt-3 inline-block text-sm underline" href="/leads">
                                Voir le pipeline
                            </a>
                        </PageSection>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}

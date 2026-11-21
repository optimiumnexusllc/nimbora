"use client";

import {
    Bot,
    CheckCircle2,
    Pause,
    PhoneCall,
    PhoneOff,
    Play,
    Plug,
    RefreshCw,
    Settings2,
    Sparkles,
    Trash2,
    TriangleAlert,
    Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    agentActionApiV1PbxAgentsAgentNumberActionPost,
    applyBrandingApiV1PbxBrandingApplyPost,
    callLogsApiV1PbxCallLogsGet,
    connectEventsApiV1PbxEventsConnectPost,
    getWorkflowsSummaryApiV1WorkflowSummaryGet,
    hangupCallApiV1PbxCallsCallIdHangupPost,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
    readConnectionApiV1PbxConnectionGet,
    readInventoryApiV1PbxInventoryGet,
    routeNumberApiV1PbxRoutesPost,
    saveConnectionApiV1PbxConnectionPut,
    testConnectionApiV1PbxConnectionTestPost,
    unrouteNumberApiV1PbxRoutesNumberDelete,
} from "@/client/sdk.gen";
import type {
    ConnectionResponse,
    TelephonyConfigurationListItem,
    WorkflowSummaryResponse,
} from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { ConnectionDialog, type ConnectionForm } from "@/components/pbx/ConnectionDialog";
import { DIRECTION_LABELS, elapsed, type PbxCallLog, type PbxInventory } from "@/components/pbx/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const REFRESH_MS = 10_000;

const fmt = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

function SectionError({ error }: { error?: string }) {
    if (!error) return null;
    return (
        <p className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            <TriangleAlert className="size-4 text-amber-400" /> Indisponible pour le moment : {error}
        </p>
    );
}

function Empty({ children }: { children: React.ReactNode }) {
    return <p className="py-8 text-center text-sm text-muted-foreground">{children}</p>;
}

export default function PbxPage() {
    const { user, loading: authLoading } = useAuth();
    const [connection, setConnection] = useState<ConnectionResponse | null>(null);
    const [inventory, setInventory] = useState<PbxInventory | null>(null);
    const [logs, setLogs] = useState<PbxCallLog[] | null>(null);
    const [ariConfigs, setAriConfigs] = useState<TelephonyConfigurationListItem[]>([]);
    const [workflows, setWorkflows] = useState<WorkflowSummaryResponse[]>([]);
    const [editing, setEditing] = useState(false);
    const [routing, setRouting] = useState<{ number: string; workflowId: string } | null>(null);
    const [now, setNow] = useState(() => Date.now());
    const fetched = useRef(false);

    const loadInventory = useCallback(async () => {
        const response = await readInventoryApiV1PbxInventoryGet();
        if (response.error) {
            setInventory(null);
            return;
        }
        setInventory(response.data as unknown as PbxInventory);
        setNow(Date.now());
    }, []);

    const loadConnection = useCallback(async () => {
        const response = await readConnectionApiV1PbxConnectionGet();
        if (response.error) {
            toast.error(detailFromError(response.error, "Chargement impossible"));
            return null;
        }
        setConnection(response.data ?? null);
        return response.data ?? null;
    }, []);

    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void (async () => {
            const [current, configs, flows] = await Promise.all([
                loadConnection(),
                listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet(),
                getWorkflowsSummaryApiV1WorkflowSummaryGet(),
            ]);
            setAriConfigs((configs.data?.configurations ?? []).filter((c) => c.provider === "ari"));
            setWorkflows((flows.data as WorkflowSummaryResponse[] | undefined) ?? []);
            if (current?.configured) void loadInventory();
        })();
    }, [authLoading, user, loadConnection, loadInventory]);

    useEffect(() => {
        if (!connection?.configured) return;
        const timer = setInterval(() => void loadInventory(), REFRESH_MS);
        return () => clearInterval(timer);
    }, [connection?.configured, loadInventory]);

    const pbxName = connection?.brand.pbx_name ?? "Téléphonie d'entreprise";

    const save = async (form: ConnectionForm) => {
        const response = await saveConnectionApiV1PbxConnectionPut({
            body: {
                ...form,
                tenant_uuid: form.tenant_uuid || null,
                incall_context: form.incall_context || null,
            },
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return false;
        }
        setConnection(response.data);
        if (response.data.status === "ok") {
            toast.success(`Connecté à ${pbxName}`);
            void loadInventory();
        } else {
            toast.error(response.data.last_error ?? "Le PBX ne répond pas");
        }
        return true;
    };

    const run = async (
        action: () => Promise<{ error?: unknown }>,
        success: string,
        fallback: string,
    ) => {
        const response = await action();
        if (response.error) {
            toast.error(detailFromError(response.error, fallback));
            return false;
        }
        toast.success(success);
        return true;
    };

    const test = async () => {
        const response = await testConnectionApiV1PbxConnectionTestPost();
        if (response.data) setConnection(response.data);
        if (response.data?.status === "ok") {
            toast.success("Le PBX répond");
            void loadInventory();
        } else {
            toast.error(response.data?.last_error ?? detailFromError(response.error, "Le PBX ne répond pas"));
        }
    };

    const loadLogs = async () => {
        const response = await callLogsApiV1PbxCallLogsGet({ query: { limit: 50 } });
        setLogs(response.error ? [] : ((response.data as unknown as PbxCallLog[]) ?? []));
    };

    if (!connection) {
        return (
            <PageLayout title="Téléphonie d'entreprise">
                <Skeleton className="h-64 w-full" />
            </PageLayout>
        );
    }

    const dialog = (
        <ConnectionDialog
            open={editing}
            onOpenChange={setEditing}
            connection={connection}
            ariConfigurations={ariConfigs}
            onSave={save}
            pbxName={pbxName}
        />
    );

    if (!connection.configured) {
        return (
            <PageLayout
                title={pbxName}
                description="Le PBX d'entreprise : postes, files d'attente, agents, numéros et serveurs vocaux, piloté depuis cette console et ouvert à vos agents IA."
            >
                <div className="card-weave flex flex-col items-center gap-4 rounded-xl border border-border/60 p-10 text-center">
                    <div className="flex size-12 items-center justify-center rounded-xl bg-gradient-to-br from-brand-cyan to-brand-violet text-white">
                        <Plug className="size-6" />
                    </div>
                    <div className="max-w-xl space-y-2">
                        <h2 className="font-display text-xl font-semibold">Connectez votre PBX</h2>
                        <p className="text-sm text-muted-foreground">
                            Installez {pbxName} sur un serveur dédié avec le kit <code>deploy/pbx</code> (une commande,
                            marque blanche incluse), puis saisissez ici l&apos;adresse et le compte de service affichés
                            à la fin de l&apos;installation.
                        </p>
                    </div>
                    <Button onClick={() => setEditing(true)}>
                        <Plug /> Connecter le PBX
                    </Button>
                </div>
                {dialog}
            </PageLayout>
        );
    }

    const errors = inventory?.errors ?? {};
    const ok = connection.status === "ok";
    const agentAction = async (number: string, action: "pause" | "unpause" | "logoff") => {
        const labels = { pause: "Agent en pause", unpause: "Agent disponible", logoff: "Agent déconnecté" };
        if (
            await run(
                () =>
                    agentActionApiV1PbxAgentsAgentNumberActionPost({
                        path: { agent_number: number, action },
                        body: action === "pause" ? { reason: "Superviseur" } : {},
                    }),
                labels[action],
                "Action impossible",
            )
        )
            void loadInventory();
    };

    return (
        <PageLayout
            title={pbxName}
            description="Le PBX d'entreprise en temps réel : appels, agents, files, postes et numéros. Routez un numéro vers un agent IA en un clic."
            actions={
                <>
                    <Button variant="outline" onClick={() => void loadInventory()}>
                        <RefreshCw /> Actualiser
                    </Button>
                    <Button variant="outline" onClick={() => setEditing(true)}>
                        <Settings2 /> Connexion
                    </Button>
                </>
            }
        >
            <div className="card-weave flex flex-wrap items-center gap-4 rounded-xl border border-border/60 p-4" data-testid="pbx-status">
                <span className={cn("size-2.5 rounded-full", ok ? "bg-emerald-400" : "bg-red-400")} />
                <div className="min-w-0 flex-1">
                    <p className="font-medium">
                        {ok ? "Connecté" : "Injoignable"} · {connection.name}
                        {connection.engine_version && (
                            <span className="ml-2 text-sm font-normal text-muted-foreground">
                                version {connection.engine_version}
                            </span>
                        )}
                    </p>
                    <p className="truncate text-sm text-muted-foreground">
                        {ok ? connection.base_url : connection.last_error} · vérifié le {fmt(connection.last_checked_at)}
                    </p>
                </div>
                <Button variant="ghost" size="sm" onClick={test}>
                    <RefreshCw /> Tester
                </Button>
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                        if (await run(() => applyBrandingApiV1PbxBrandingApplyPost(), `Marque appliquée : ${connection.brand.sip_user_agent}`, "Application impossible"))
                            void loadConnection();
                    }}
                >
                    <Sparkles /> {connection.branding_applied_at ? "Marque appliquée" : "Appliquer la marque"}
                </Button>
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                        if (await run(() => connectEventsApiV1PbxEventsConnectPost(), "Événements d'appels reçus par la plateforme", "Abonnement impossible"))
                            void loadConnection();
                    }}
                >
                    {connection.events_connected ? <CheckCircle2 className="text-emerald-400" /> : <Waypoints />}
                    {connection.events_connected ? "Événements reçus" : "Recevoir les événements"}
                </Button>
            </div>

            {!inventory ? (
                <Skeleton className="h-72 w-full" />
            ) : (
                <Tabs
                    defaultValue="calls"
                    onValueChange={(v) => v === "logs" && logs === null && void loadLogs()}
                    className="space-y-4"
                >
                    <TabsList className="flex-wrap">
                        <TabsTrigger value="calls">Appels en cours ({inventory.calls.length})</TabsTrigger>
                        <TabsTrigger value="agents">Agents ({inventory.agents.length})</TabsTrigger>
                        <TabsTrigger value="queues">Files ({inventory.queues.length})</TabsTrigger>
                        <TabsTrigger value="users">Postes ({inventory.users.length})</TabsTrigger>
                        <TabsTrigger value="numbers">Numéros ({inventory.numbers.length})</TabsTrigger>
                        <TabsTrigger value="logs">Journal</TabsTrigger>
                    </TabsList>

                    <TabsContent value="calls">
                        <PageSection title="Appels en cours">
                            <SectionError error={errors.calls} />
                            {inventory.calls.length === 0 ? (
                                <Empty>Aucun appel en cours.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Appelant</TableHead>
                                            <TableHead>En ligne avec</TableHead>
                                            <TableHead>Sens</TableHead>
                                            <TableHead>Durée</TableHead>
                                            <TableHead />
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {inventory.calls.map((call) => (
                                            <TableRow key={call.call_id} data-testid="pbx-call">
                                                <TableCell>
                                                    <div className="font-medium">{call.caller_name || call.caller}</div>
                                                    <div className="font-mono text-xs text-muted-foreground">{call.caller}</div>
                                                </TableCell>
                                                <TableCell>{call.peer_name || call.peer || "—"}</TableCell>
                                                <TableCell>
                                                    {DIRECTION_LABELS[call.direction ?? ""] ?? call.direction ?? "—"}
                                                    {call.on_hold && <Badge variant="secondary" className="ml-2">En attente</Badge>}
                                                </TableCell>
                                                <TableCell className="font-mono">{elapsed(call.since, now)}</TableCell>
                                                <TableCell className="text-right">
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="text-destructive"
                                                        onClick={async () => {
                                                            if (!window.confirm("Raccrocher cet appel ?")) return;
                                                            if (await run(() => hangupCallApiV1PbxCallsCallIdHangupPost({ path: { call_id: call.call_id } }), "Appel raccroché", "Impossible de raccrocher"))
                                                                void loadInventory();
                                                        }}
                                                    >
                                                        <PhoneOff /> Raccrocher
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>

                    <TabsContent value="agents">
                        <PageSection title="Agents du centre d'appels">
                            <SectionError error={errors.agents ?? errors.agent_statuses} />
                            {inventory.agents.length === 0 ? (
                                <Empty>Aucun agent défini sur le PBX.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Agent</TableHead>
                                            <TableHead>État</TableHead>
                                            <TableHead>Poste</TableHead>
                                            <TableHead />
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {inventory.agents.map((agent) => (
                                            <TableRow key={agent.id} data-testid="pbx-agent">
                                                <TableCell>
                                                    <div className="font-medium">{agent.name}</div>
                                                    <div className="font-mono text-xs text-muted-foreground">n° {agent.number}</div>
                                                </TableCell>
                                                <TableCell>
                                                    {!agent.logged ? (
                                                        <Badge variant="outline">Déconnecté</Badge>
                                                    ) : agent.paused ? (
                                                        <Badge variant="secondary" className="text-amber-300">
                                                            En pause{agent.paused_reason ? ` · ${agent.paused_reason}` : ""}
                                                        </Badge>
                                                    ) : (
                                                        <Badge className="bg-emerald-600 text-white">Disponible</Badge>
                                                    )}
                                                </TableCell>
                                                <TableCell className="font-mono text-sm">{agent.extension ?? "—"}</TableCell>
                                                <TableCell className="space-x-1 text-right">
                                                    {agent.logged && (agent.paused ? (
                                                        <Button variant="ghost" size="sm" onClick={() => agentAction(agent.number, "unpause")}>
                                                            <Play /> Reprendre
                                                        </Button>
                                                    ) : (
                                                        <Button variant="ghost" size="sm" onClick={() => agentAction(agent.number, "pause")}>
                                                            <Pause /> Pause
                                                        </Button>
                                                    ))}
                                                    {agent.logged && (
                                                        <Button variant="ghost" size="sm" onClick={() => agentAction(agent.number, "logoff")}>
                                                            Déconnecter
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>

                    <TabsContent value="queues">
                        <PageSection title="Files d'attente">
                            <SectionError error={errors.queues} />
                            {inventory.queues.length === 0 ? (
                                <Empty>Aucune file d&apos;attente.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>File</TableHead>
                                            <TableHead>Numéros</TableHead>
                                            <TableHead className="text-right">Membres</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {inventory.queues.map((queue) => (
                                            <TableRow key={queue.id}>
                                                <TableCell className="font-medium">{queue.name}</TableCell>
                                                <TableCell className="font-mono text-sm">{queue.extensions.join(", ") || "—"}</TableCell>
                                                <TableCell className="text-right">{queue.members}</TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>

                    <TabsContent value="users">
                        <PageSection title="Postes et utilisateurs">
                            <SectionError error={errors.users} />
                            {inventory.users.length === 0 ? (
                                <Empty>Aucun poste.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Utilisateur</TableHead>
                                            <TableHead>Poste</TableHead>
                                            <TableHead>E-mail</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {inventory.users.map((u) => (
                                            <TableRow key={u.uuid}>
                                                <TableCell className="font-medium">{u.name}</TableCell>
                                                <TableCell className="font-mono">{u.extension ?? "—"}</TableCell>
                                                <TableCell className="text-sm text-muted-foreground">{u.email ?? "—"}</TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>

                    <TabsContent value="numbers">
                        <PageSection
                            title="Numéros entrants"
                            actions={
                                <Button onClick={() => setRouting({ number: "", workflowId: "" })} disabled={!connection.ari_configuration_id}>
                                    <Bot /> Router un numéro vers un agent IA
                                </Button>
                            }
                        >
                            {!connection.ari_configuration_id && (
                                <p className="mb-3 text-sm text-muted-foreground">
                                    Pour router des numéros vers vos agents IA, reliez une configuration ARI dans « Connexion ».
                                </p>
                            )}
                            <SectionError error={errors.incalls} />
                            {inventory.numbers.length === 0 ? (
                                <Empty>Aucun numéro entrant.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Numéro</TableHead>
                                            <TableHead>Destination</TableHead>
                                            <TableHead />
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {inventory.numbers.map((n) => (
                                            <TableRow key={`${n.incall_id}-${n.number}`} data-testid="pbx-number">
                                                <TableCell className="font-mono">{n.number}</TableCell>
                                                <TableCell>
                                                    {n.ai_workflow_name ? (
                                                        <span className="flex items-center gap-1.5">
                                                            <Bot className="size-4 text-brand-cyan" /> Agent IA « {n.ai_workflow_name} »
                                                        </span>
                                                    ) : (
                                                        <>
                                                            {n.destination}
                                                            {n.description && <span className="text-muted-foreground"> · {n.description}</span>}
                                                        </>
                                                    )}
                                                </TableCell>
                                                <TableCell className="text-right">
                                                    {n.ai_workflow_id && (
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            className="text-destructive"
                                                            onClick={async () => {
                                                                if (!window.confirm(`Retirer l'agent IA du numéro ${n.number} ?`)) return;
                                                                if (await run(() => unrouteNumberApiV1PbxRoutesNumberDelete({ path: { number: n.number } }), "Routage retiré", "Impossible de retirer le routage"))
                                                                    void loadInventory();
                                                            }}
                                                        >
                                                            <Trash2 /> Retirer
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>

                    <TabsContent value="logs">
                        <PageSection title="Derniers appels">
                            {logs === null ? (
                                <Skeleton className="h-40" />
                            ) : logs.length === 0 ? (
                                <Empty>Aucun appel récent.</Empty>
                            ) : (
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Date</TableHead>
                                            <TableHead>De</TableHead>
                                            <TableHead>Vers</TableHead>
                                            <TableHead>Sens</TableHead>
                                            <TableHead className="text-right">Durée</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {logs.map((log) => (
                                            <TableRow key={log.id}>
                                                <TableCell className="text-sm">{fmt(log.start)}</TableCell>
                                                <TableCell>{log.source_name || log.source}</TableCell>
                                                <TableCell>{log.destination_name || log.destination}</TableCell>
                                                <TableCell>{DIRECTION_LABELS[log.direction ?? ""] ?? "—"}</TableCell>
                                                <TableCell className="text-right">
                                                    {log.answered ? (
                                                        `${Math.max(1, Math.round((log.duration ?? 0) / 60))} min`
                                                    ) : (
                                                        <Badge variant="outline" className="text-red-300">
                                                            <PhoneCall className="size-3" /> Manqué
                                                        </Badge>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}
                        </PageSection>
                    </TabsContent>
                </Tabs>
            )}

            {dialog}

            <Dialog open={routing !== null} onOpenChange={(open) => !open && setRouting(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Router un numéro vers un agent IA</DialogTitle>
                        <DialogDescription>
                            Le numéro est créé sur le PBX et les appels sont décrochés par l&apos;agent choisi. Un numéro qui
                            a déjà une destination (poste, file…) n&apos;est jamais écrasé.
                        </DialogDescription>
                    </DialogHeader>
                    {routing && (
                        <div className="space-y-3">
                            <div className="space-y-1">
                                <Label htmlFor="route-number">Numéro</Label>
                                <Input
                                    id="route-number"
                                    placeholder="+225 27 00 00 00 99"
                                    value={routing.number}
                                    onChange={(e) => setRouting({ ...routing, number: e.target.value })}
                                />
                            </div>
                            <div className="space-y-1">
                                <Label>Agent IA</Label>
                                <Select value={routing.workflowId} onValueChange={(v) => setRouting({ ...routing, workflowId: v })}>
                                    <SelectTrigger aria-label="Agent IA" className="w-full">
                                        <SelectValue placeholder="Choisir un agent" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {workflows.map((w) => (
                                            <SelectItem key={w.id} value={String(w.id)}>
                                                {w.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setRouting(null)}>
                            Annuler
                        </Button>
                        <Button
                            disabled={!routing?.number.trim() || !routing?.workflowId}
                            onClick={async () => {
                                if (!routing) return;
                                const done = await run(
                                    () =>
                                        routeNumberApiV1PbxRoutesPost({
                                            body: { number: routing.number, workflow_id: Number(routing.workflowId) },
                                        }),
                                    `Le ${routing.number} sonne maintenant chez l'agent IA`,
                                    "Routage impossible",
                                );
                                if (done) {
                                    setRouting(null);
                                    void loadInventory();
                                }
                            }}
                        >
                            <Bot /> Router
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageLayout>
    );
}

"use client";

import {
    Bot,
    Cable,
    CheckCircle2,
    Clock,
    Pause,
    Pencil,
    PhoneCall,
    PhoneForwarded,
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
    listMenusApiV1PbxMenusGet,
    listOutboundRoutesApiV1PbxOutboundRoutesGet,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
    listTrunksApiV1PbxTrunksGet,
    listVoicemailsApiV1PbxVoicemailsGet,
    readConnectionApiV1PbxConnectionGet,
    readInventoryApiV1PbxInventoryGet,
    removeNumberApiV1PbxNumbersNumberDelete,
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
import { AiOutboundCard } from "@/components/pbx/AiOutboundCard";
import { ConnectionDialog, type ConnectionForm } from "@/components/pbx/ConnectionDialog";
import type { Destination, DestinationSources, PbxVoicemail } from "@/components/pbx/DestinationPicker";
import { ExtensionsTab } from "@/components/pbx/ExtensionsTab";
import { MenusTab } from "@/components/pbx/MenusTab";
import { NumberDialog, type NumberEdit } from "@/components/pbx/NumberDialog";
import { QueuesTab } from "@/components/pbx/QueuesTab";
import { RestrictionsSection } from "@/components/pbx/RestrictionsSection";
import { ScheduleDialog } from "@/components/pbx/ScheduleDialog";
import { TrunksTab } from "@/components/pbx/TrunksTab";
import {
    DIRECTION_LABELS,
    elapsed,
    type PatternPreset,
    type PbxCallLog,
    type PbxInventory,
    type PbxMenu,
    type PbxNumber,
    type PbxOutboundRoute,
    type PbxTrunk,
} from "@/components/pbx/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
    const [numberEdit, setNumberEdit] = useState<NumberEdit | null>(null);
    const [menus, setMenus] = useState<PbxMenu[]>([]);
    const [voicemails, setVoicemails] = useState<PbxVoicemail[]>([]);
    const [lines, setLines] = useState<{
        trunks: PbxTrunk[];
        routes: PbxOutboundRoute[];
        presets: PatternPreset[];
        error: string | null;
    } | null>(null);
    const [scheduling, setScheduling] = useState(false);
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

    const loadMenus = useCallback(async () => {
        const response = await listMenusApiV1PbxMenusGet();
        if (!response.error) setMenus((response.data as unknown as PbxMenu[]) ?? []);
    }, []);

    const loadVoicemails = useCallback(async () => {
        const response = await listVoicemailsApiV1PbxVoicemailsGet();
        if (!response.error) setVoicemails((response.data as unknown as PbxVoicemail[]) ?? []);
    }, []);

    const loadLines = useCallback(async () => {
        const [trunks, routes] = await Promise.all([listTrunksApiV1PbxTrunksGet(), listOutboundRoutesApiV1PbxOutboundRoutesGet()]);
        const t = trunks.data as { trunks: PbxTrunk[]; status_error: string | null } | undefined;
        const r = routes.data as { routes: PbxOutboundRoute[]; presets: PatternPreset[] } | undefined;
        setLines({
            trunks: t?.trunks ?? [],
            routes: r?.routes ?? [],
            presets: r?.presets ?? [],
            error: trunks.error ? detailFromError(trunks.error, "Lignes indisponibles") : (t?.status_error ?? null),
        });
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
            if (current?.configured) {
                void loadInventory();
                void loadMenus();
                void loadVoicemails();
            }
        })();
    }, [authLoading, user, loadConnection, loadInventory, loadMenus, loadVoicemails]);

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
    const sources: DestinationSources = {
        queues: inventory?.queues ?? [],
        users: inventory?.users ?? [],
        voicemails,
        workflows,
        menus: menus.map((m) => ({ id: m.id, name: m.name, published: Boolean(m.pbx_ivr_id) })),
        aiEnabled: Boolean(connection.ari_configuration_id),
    };
    const menuByIvr = new Map(menus.filter((m) => m.pbx_ivr_id).map((m) => [m.pbx_ivr_id as number, m]));
    const currentDestination = (n: PbxNumber): Destination => {
        const target = n.destination_target_id ?? null;
        switch (n.destination_type) {
            case "ai":
                return { type: "ai", target_id: n.ai_workflow_id };
            case "ivr": {
                const menu = target != null ? menuByIvr.get(target) : undefined;
                return menu ? { type: "menu", target_id: menu.id } : { type: "hangup", target_id: null };
            }
            case "queue":
            case "user":
            case "voicemail":
                return { type: n.destination_type, target_id: target };
            default:
                return { type: "hangup", target_id: null };
        }
    };
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
            description="Le PBX d'entreprise en temps réel : appels, agents, files, postes, numéros, serveurs vocaux et lignes opérateurs. Un agent IA derrière n'importe quel numéro ou touche."
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
                    onValueChange={(v) => {
                        if (v === "logs" && logs === null) void loadLogs();
                        if (v === "lines" && lines === null) void loadLines();
                        if (v === "menus") void loadMenus();
                    }}
                    className="space-y-4"
                >
                    <TabsList className="flex-wrap">
                        <TabsTrigger value="calls">Appels en cours ({inventory.calls.length})</TabsTrigger>
                        <TabsTrigger value="agents">Agents ({inventory.agents.length})</TabsTrigger>
                        <TabsTrigger value="queues">Files ({inventory.queues.length})</TabsTrigger>
                        <TabsTrigger value="users">Postes ({inventory.users.length})</TabsTrigger>
                        <TabsTrigger value="numbers">Numéros ({inventory.numbers.length})</TabsTrigger>
                        <TabsTrigger value="menus">Serveurs vocaux ({menus.length})</TabsTrigger>
                        <TabsTrigger value="lines">
                            <Cable className="size-3.5" /> Lignes opérateurs
                        </TabsTrigger>
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
                        <QueuesTab
                            queues={inventory.queues}
                            agents={inventory.agents}
                            workflows={workflows}
                            aiEnabled={Boolean(connection.ari_configuration_id)}
                            error={errors.queues}
                            onChanged={() => void loadInventory()}
                        />
                    </TabsContent>

                    <TabsContent value="users">
                        <ExtensionsTab users={inventory.users} error={errors.users} onChanged={() => void loadInventory()} />
                    </TabsContent>

                    <TabsContent value="numbers">
                        <PageSection
                            title="Numéros entrants"
                            actions={
                                <>
                                    <Button variant="outline" onClick={() => setScheduling(true)}>
                                        <Clock /> Horaires
                                    </Button>
                                    <Button
                                        onClick={() =>
                                            setNumberEdit({
                                                number: "",
                                                existing: false,
                                                destination: connection.ari_configuration_id && workflows[0]
                                                    ? { type: "ai", target_id: workflows[0].id }
                                                    : { type: "hangup", target_id: null },
                                            })
                                        }
                                    >
                                        <PhoneForwarded /> Ajouter un numéro
                                    </Button>
                                </>
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
                                                            {n.destination_type === "ivr" && menuByIvr.get(n.destination_target_id ?? -1)
                                                                ? `Serveur vocal « ${menuByIvr.get(n.destination_target_id ?? -1)?.name} »`
                                                                : n.destination}
                                                            {n.description && <span className="text-muted-foreground"> · {n.description}</span>}
                                                            {n.schedules?.some((name) => name.startsWith("nimbora-horaires")) && (
                                                                <Badge variant="outline" className="ml-2 gap-1">
                                                                    <Clock className="size-3" /> Horaires de l&apos;entreprise
                                                                </Badge>
                                                            )}
                                                        </>
                                                    )}
                                                </TableCell>
                                                <TableCell className="whitespace-nowrap text-right">
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        aria-label={`Modifier la destination du ${n.number}`}
                                                        onClick={() => setNumberEdit({ number: n.number, existing: true, destination: currentDestination(n) })}
                                                    >
                                                        <Pencil /> Destination
                                                    </Button>
                                                    {!n.ai_workflow_id && (
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            className="text-destructive"
                                                            aria-label={`Supprimer le numéro ${n.number}`}
                                                            onClick={async () => {
                                                                if (!window.confirm(`Supprimer le numéro ${n.number} du PBX ?`)) return;
                                                                if (await run(() => removeNumberApiV1PbxNumbersNumberDelete({ path: { number: n.number } }), "Numéro supprimé", "Suppression impossible"))
                                                                    void loadInventory();
                                                            }}
                                                        >
                                                            <Trash2 />
                                                        </Button>
                                                    )}
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

                    <TabsContent value="menus">
                        <MenusTab
                            menus={menus}
                            sources={sources}
                            onChanged={() => {
                                void loadMenus();
                                void loadInventory();
                            }}
                        />
                    </TabsContent>

                    <TabsContent value="lines">
                        {lines === null ? (
                            <Skeleton className="h-64 w-full" />
                        ) : (
                            <div className="space-y-4">
                                <TrunksTab
                                    trunks={lines.trunks}
                                    routes={lines.routes}
                                    presets={lines.presets}
                                    error={lines.error}
                                    onChanged={() => void loadLines()}
                                />
                                {connection.ari_configuration_id && (
                                    <AiOutboundCard trunks={lines.trunks} hasRoutes={lines.routes.length > 0} />
                                )}
                                <RestrictionsSection users={inventory.users} />
                            </div>
                        )}
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

            {inventory && (
                <ScheduleDialog
                    open={scheduling}
                    onOpenChange={setScheduling}
                    numbers={inventory.numbers}
                    workflows={workflows}
                    aiEnabled={Boolean(connection.ari_configuration_id)}
                    onDone={() => void loadInventory()}
                />
            )}

            <NumberDialog edit={numberEdit} onClose={() => setNumberEdit(null)} sources={sources} onDone={() => void loadInventory()} />
        </PageLayout>
    );
}

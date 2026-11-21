"use client";

import { Copy, KeyRound, Plus, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { CallbacksPanel } from "@/components/contact-center/CallbacksPanel";
import { HandoffCard } from "@/components/contact-center/HandoffCard";
import { Softphone } from "@/components/contact-center/Softphone";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/lib/auth";
import {
    type Agent,
    ApiError,
    enterpriseApi,
    type Handoff,
    type Queue,
    type SoftphoneCredentials,
} from "@/lib/enterpriseApi";

const STRATEGIES: { value: string; label: string }[] = [
    { value: "rrmemory", label: "Tour de rôle (mémoire)" },
    { value: "leastrecent", label: "Agent le moins récemment sollicité" },
    { value: "fewestcalls", label: "Agent ayant pris le moins d'appels" },
    { value: "ringall", label: "Faire sonner tout le monde" },
    { value: "random", label: "Aléatoire" },
    { value: "linear", label: "Ordre fixe" },
];

function CredentialsDialog({
    credentials,
    onClose,
}: {
    credentials: SoftphoneCredentials | null;
    onClose: () => void;
}) {
    const copy = (value: string) => {
        void navigator.clipboard.writeText(value);
        toast.success("Copié");
    };
    return (
        <Dialog open={credentials !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Identifiants du poste {credentials?.agent.extension}</DialogTitle>
                    <DialogDescription>
                        Le mot de passe n&apos;est affiché qu&apos;une seule fois : transmettez-le à l&apos;agent.
                        Il pourra se connecter depuis la page Centre d&apos;appels ou avec n&apos;importe quel
                        softphone WebRTC.
                    </DialogDescription>
                </DialogHeader>
                {credentials && (
                    <div className="space-y-3 text-sm">
                        {[
                            ["Utilisateur SIP", credentials.sip_username],
                            ["Mot de passe", credentials.sip_password],
                            ["Domaine (realm)", credentials.sip_realm],
                            ["Serveur WebSocket", credentials.wss_url ?? `wss://${window.location.host}/sip`],
                        ].map(([label, value]) => (
                            <div key={label} className="flex items-center justify-between gap-3 rounded-md border p-2">
                                <div>
                                    <div className="text-xs text-muted-foreground">{label}</div>
                                    <code className="break-all">{value}</code>
                                </div>
                                <Button variant="ghost" size="icon" onClick={() => copy(value)}>
                                    <Copy className="h-4 w-4" />
                                </Button>
                            </div>
                        ))}
                    </div>
                )}
                <DialogFooter>
                    <Button onClick={onClose}>J&apos;ai noté le mot de passe</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function QueueDialog({
    open,
    queue,
    agents,
    onClose,
    onSaved,
}: {
    open: boolean;
    queue: Queue | null;
    agents: Agent[];
    onClose: () => void;
    onSaved: () => void;
}) {
    const [slug, setSlug] = useState("");
    const [name, setName] = useState("");
    const [strategy, setStrategy] = useState("rrmemory");
    const [maxWait, setMaxWait] = useState(300);
    const [overflow, setOverflow] = useState("");
    const [members, setMembers] = useState<number[]>([]);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open) return;
        setSlug(queue?.slug ?? "");
        setName(queue?.name ?? "");
        setStrategy(queue?.strategy ?? "rrmemory");
        setMaxWait(queue?.max_wait_seconds ?? 300);
        setOverflow(queue?.overflow_destination ?? "");
        setMembers(queue?.agents.map((a) => a.id) ?? []);
    }, [open, queue]);

    const save = async () => {
        setSaving(true);
        try {
            const input = {
                name,
                strategy,
                max_wait_seconds: maxWait,
                overflow_destination: overflow || null,
                agent_ids: members,
            };
            if (queue) await enterpriseApi.updateQueue(queue.id, input);
            else await enterpriseApi.createQueue({ ...input, slug });
            toast.success("File d'attente enregistrée");
            onSaved();
            onClose();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Enregistrement impossible");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{queue ? `File « ${queue.name} »` : "Nouvelle file d'attente"}</DialogTitle>
                    <DialogDescription>
                        Les agents IA y transfèrent un appel avec la destination <code>queue:{slug || "identifiant"}</code>.
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                    {!queue && (
                        <div className="space-y-1">
                            <Label htmlFor="q-slug">Identifiant</Label>
                            <Input
                                id="q-slug"
                                placeholder="support"
                                value={slug}
                                onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
                            />
                        </div>
                    )}
                    <div className="space-y-1">
                        <Label htmlFor="q-name">Nom</Label>
                        <Input id="q-name" placeholder="Service client" value={name} onChange={(e) => setName(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label>Distribution des appels</Label>
                        <Select value={strategy} onValueChange={setStrategy}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {STRATEGIES.map((s) => (
                                    <SelectItem key={s.value} value={s.value}>
                                        {s.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1">
                            <Label htmlFor="q-wait">Attente maximale (s)</Label>
                            <Input
                                id="q-wait"
                                type="number"
                                min={10}
                                max={3600}
                                value={maxWait}
                                onChange={(e) => setMaxWait(Number(e.target.value))}
                            />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="q-overflow">Débordement (poste ou n°)</Label>
                            <Input
                                id="q-overflow"
                                placeholder="1001 ou +33…"
                                value={overflow}
                                onChange={(e) => setOverflow(e.target.value)}
                            />
                        </div>
                    </div>
                    <div className="space-y-2">
                        <Label>Agents membres</Label>
                        {agents.length === 0 && (
                            <p className="text-sm text-muted-foreground">Créez d&apos;abord des postes d&apos;agents.</p>
                        )}
                        {agents.map((agent) => (
                            <label key={agent.id} className="flex items-center gap-2 text-sm">
                                <Checkbox
                                    checked={members.includes(agent.id)}
                                    onCheckedChange={(checked) =>
                                        setMembers((prev) =>
                                            checked ? [...prev, agent.id] : prev.filter((id) => id !== agent.id),
                                        )
                                    }
                                />
                                {agent.display_name} ({agent.extension})
                            </label>
                        ))}
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button onClick={save} disabled={saving || !name || (!queue && !slug)}>
                        Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function ContactCenterPage() {
    const { user, loading } = useAuth();
    const [queues, setQueues] = useState<Queue[] | null>(null);
    const [agents, setAgents] = useState<Agent[]>([]);
    const [seat, setSeat] = useState<Agent | null>(null);
    const [handoffs, setHandoffs] = useState<Handoff[]>([]);
    const [openHandoff, setOpenHandoff] = useState<string | null>(null);
    const [unavailable, setUnavailable] = useState<string | null>(null);
    const [credentials, setCredentials] = useState<SoftphoneCredentials | null>(null);
    const [queueDialog, setQueueDialog] = useState<{ open: boolean; queue: Queue | null }>({
        open: false,
        queue: null,
    });
    const [newAgentName, setNewAgentName] = useState("");
    const [newAgentExt, setNewAgentExt] = useState("");

    const load = useCallback(async () => {
        try {
            const [q, a, me] = await Promise.all([
                enterpriseApi.listQueues(),
                enterpriseApi.listAgents(),
                enterpriseApi.mySeat(),
            ]);
            setQueues(q);
            setAgents(a);
            setSeat(me);
            enterpriseApi.listHandoffs().then(setHandoffs).catch(() => undefined);
        } catch (e) {
            if (e instanceof ApiError && (e.status === 404 || e.status === 402)) {
                setUnavailable(
                    e.status === 402
                        ? "Votre offre n'inclut pas le centre d'appels humain."
                        : "Le centre d'appels humain n'est pas activé sur cette plateforme.",
                );
            } else {
                toast.error(e instanceof Error ? e.message : "Chargement impossible");
            }
        }
    }, []);

    useEffect(() => {
        if (!loading && user) void load();
    }, [loading, user, load]);

    const createAgent = async () => {
        try {
            const created = await enterpriseApi.createAgent({
                display_name: newAgentName,
                extension: newAgentExt,
            });
            setCredentials(created);
            setNewAgentName("");
            setNewAgentExt("");
            void load();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Création impossible");
        }
    };

    const resetPassword = async (agent: Agent) => {
        try {
            setCredentials(await enterpriseApi.resetAgentPassword(agent.id));
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Réinitialisation impossible");
        }
    };

    const claimSeat = async (agent: Agent) => {
        try {
            await enterpriseApi.claimSeat(agent.id);
            toast.success(`Le poste ${agent.extension} est relié à votre compte.`);
            void load();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Impossible de relier ce poste");
        }
    };

    const removeAgent = async (agent: Agent) => {
        if (!window.confirm(`Supprimer le poste ${agent.extension} (${agent.display_name}) ?`)) return;
        await enterpriseApi.deleteAgent(agent.id).catch((e) => toast.error(String(e.message ?? e)));
        void load();
    };

    const removeQueue = async (queue: Queue) => {
        if (!window.confirm(`Supprimer la file « ${queue.name} » ?`)) return;
        await enterpriseApi.deleteQueue(queue.id).catch((e) => toast.error(String(e.message ?? e)));
        void load();
    };

    const toggleAgent = async (agent: Agent) => {
        try {
            await enterpriseApi.updateAgent(agent.id, { is_active: !agent.is_active });
            void load();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Modification impossible");
        }
    };

    const toggleSupervisor = async (agent: Agent) => {
        try {
            await enterpriseApi.updateAgent(agent.id, { is_supervisor: !agent.is_supervisor });
            toast.success(
                agent.is_supervisor
                    ? `${agent.display_name} n'est plus superviseur.`
                    : `${agent.display_name} peut écouter, chuchoter et intervenir dans les appels.`,
            );
            void load();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Modification impossible");
        }
    };

    if (unavailable) {
        return (
            <PageLayout title="Centre d'appels">
                <Card>
                    <CardContent className="pt-6 text-muted-foreground">{unavailable}</CardContent>
                </Card>
            </PageLayout>
        );
    }

    if (queues === null) {
        return (
            <PageLayout title="Centre d'appels">
                <Skeleton className="h-48 w-full" />
            </PageLayout>
        );
    }

    return (
        <PageLayout
            title="Centre d'appels"
            description="Agents humains, files d'attente et transfert des appels depuis les agents IA."
        >
            {seat && <Softphone seat={seat} />}

            {queues !== null && (
                <PageSection
                    title="Rappels"
                    description="Aucun client perdu : demandes de rappel prises par les agents IA, appels restés sans réponse dans une file, et rappels planifiés à la main."
                >
                    <CallbacksPanel
                        queues={queues}
                        seatId={seat?.is_active ? seat.id : null}
                        agentNames={Object.fromEntries(agents.map((a) => [a.id, a.display_name]))}
                    />
                </PageSection>
            )}


            <PageSection
                title="Files d'attente"
                description="Dans un agent IA, ajoutez l'outil « Transférer l'appel » avec la destination indiquée."
                actions={
                    <Button onClick={() => setQueueDialog({ open: true, queue: null })}>
                        <Plus className="mr-2 h-4 w-4" />
                        Nouvelle file
                    </Button>
                }
            >
                {queues.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucune file d&apos;attente pour l&apos;instant.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Nom</TableHead>
                                <TableHead>Destination de transfert</TableHead>
                                <TableHead>Agents</TableHead>
                                <TableHead>Attente max.</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {queues.map((queue) => (
                                <TableRow key={queue.id}>
                                    <TableCell className="font-medium">{queue.name}</TableCell>
                                    <TableCell>
                                        <code>{queue.transfer_destination}</code>
                                    </TableCell>
                                    <TableCell>
                                        {queue.agents.length ? queue.agents.map((a) => a.extension).join(", ") : "—"}
                                    </TableCell>
                                    <TableCell>{Math.round(queue.max_wait_seconds / 60)} min</TableCell>
                                    <TableCell className="text-right">
                                        <Button variant="ghost" size="sm" onClick={() => setQueueDialog({ open: true, queue })}>
                                            Modifier
                                        </Button>
                                        <Button variant="ghost" size="icon" onClick={() => removeQueue(queue)}>
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <PageSection
                title={
                    <span className="flex items-center gap-2">
                        <Users className="h-5 w-5" /> Postes d&apos;agents humains
                    </span>
                }
                description="Chaque poste dispose d'un softphone dans le navigateur (WebRTC)."
            >
                <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1">
                        <Label htmlFor="a-name">Nom de l&apos;agent</Label>
                        <Input id="a-name" value={newAgentName} onChange={(e) => setNewAgentName(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="a-ext">Poste (2 à 6 chiffres)</Label>
                        <Input
                            id="a-ext"
                            className="w-32"
                            value={newAgentExt}
                            onChange={(e) => setNewAgentExt(e.target.value.replace(/\D/g, "").slice(0, 6))}
                        />
                    </div>
                    <Button onClick={createAgent} disabled={!newAgentName || newAgentExt.length < 2}>
                        <Plus className="mr-2 h-4 w-4" />
                        Créer le poste
                    </Button>
                </div>
                {agents.length > 0 && (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Poste</TableHead>
                                <TableHead>Agent</TableHead>
                                <TableHead>Utilisateur SIP</TableHead>
                                <TableHead>Files</TableHead>
                                <TableHead>Statut</TableHead>
                                <TableHead>Superviseur</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {agents.map((agent) => (
                                <TableRow key={agent.id}>
                                    <TableCell className="font-medium">{agent.extension}</TableCell>
                                    <TableCell>{agent.display_name}</TableCell>
                                    <TableCell>
                                        <code>{agent.sip_username}</code>
                                    </TableCell>
                                    <TableCell>{agent.queues.join(", ") || "—"}</TableCell>
                                    <TableCell>
                                        <Badge
                                            variant={agent.is_active ? "default" : "secondary"}
                                            className="cursor-pointer"
                                            onClick={() => toggleAgent(agent)}
                                        >
                                            {agent.is_active ? "Actif" : "Désactivé"}
                                        </Badge>
                                        {agent.presence === "paused" && (
                                            <span className="ml-2 text-xs text-amber-300">
                                                En pause{agent.presence_reason ? ` · ${agent.presence_reason}` : ""}
                                            </span>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <Switch
                                            aria-label={`Droits superviseur pour ${agent.display_name}`}
                                            checked={Boolean(agent.is_supervisor)}
                                            onCheckedChange={() => toggleSupervisor(agent)}
                                        />
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {agent.user_id === null && !seat && (
                                            <Button variant="ghost" size="sm" onClick={() => claimSeat(agent)}>
                                                C&apos;est mon poste
                                            </Button>
                                        )}
                                        <Button variant="ghost" size="sm" onClick={() => resetPassword(agent)}>
                                            <KeyRound className="mr-1 h-4 w-4" />
                                            Nouveau mot de passe
                                        </Button>
                                        <Button variant="ghost" size="icon" onClick={() => removeAgent(agent)}>
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <PageSection
                title="Passations récentes"
                description="Ce que les agents IA ont transmis à vos équipes au moment du transfert."
            >
                {handoffs.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                        Aucune passation pour l&apos;instant. Elles apparaissent dès qu&apos;un agent IA transfère un
                        appel vers une file (destination <code>queue:…</code>).
                    </p>
                ) : (
                    <div className="space-y-2">
                        {handoffs.map((h) => (
                            <div key={h.id} className="rounded-lg border border-border/60">
                                <button
                                    type="button"
                                    onClick={() => setOpenHandoff(openHandoff === h.id ? null : h.id)}
                                    className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left text-sm hover:bg-accent/40"
                                >
                                    <span className="font-medium">{h.customer_name || h.caller_number || "Client"}</span>
                                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                                        {h.reason || "Résumé indisponible"}
                                    </span>
                                    {h.queue_slug && <Badge variant="secondary">{h.queue_slug}</Badge>}
                                    <Badge variant={h.status === "answered" ? "default" : "secondary"}>
                                        {h.status === "answered"
                                            ? "Pris en charge"
                                            : h.status === "abandoned"
                                              ? "Sans réponse → rappel"
                                              : "En attente"}
                                    </Badge>
                                    <span className="text-xs text-muted-foreground">
                                        {h.created_at ? new Date(h.created_at).toLocaleString("fr-FR") : ""}
                                    </span>
                                </button>
                                {openHandoff === h.id && (
                                    <div className="border-t border-border/60 p-3">
                                        <HandoffCard handoff={h} />
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </PageSection>

            <QueueDialog
                open={queueDialog.open}
                queue={queueDialog.queue}
                agents={agents.filter((a) => a.is_active)}
                onClose={() => setQueueDialog({ open: false, queue: null })}
                onSaved={load}
            />
            <CredentialsDialog credentials={credentials} onClose={() => setCredentials(null)} />
        </PageLayout>
    );
}

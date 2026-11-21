"use client";

import { Bot, ListPlus, Trash2, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    addQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdPut,
    createQueueApiV1PbxQueuesPost,
    deleteQueueApiV1PbxQueuesQueueIdDelete,
    queueOverflowApiV1PbxQueuesQueueIdOverflowPut,
    removeQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdDelete,
    strategiesApiV1PbxStrategiesGet,
} from "@/client/sdk.gen";
import type { WorkflowSummaryResponse } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";

import type { PbxAgent, PbxQueue } from "./types";

type NewQueue = {
    label: string;
    extension: string;
    strategy: string;
    ring_seconds: number;
    agent_ids: number[];
    overflow: string; // "none" or workflow id
    overflow_after_seconds: number;
};
const EMPTY: NewQueue = { label: "", extension: "", strategy: "leastrecent", ring_seconds: 20, agent_ids: [], overflow: "none", overflow_after_seconds: 60 };

function AgentPicker({ agents, selected, onChange }: { agents: PbxAgent[]; selected: number[]; onChange: (ids: number[]) => void }) {
    if (agents.length === 0) return <p className="text-sm text-muted-foreground">Aucun agent : créez des postes « agent ».</p>;
    return (
        <div className="grid max-h-48 gap-1 overflow-auto rounded-md border border-border/60 p-2 sm:grid-cols-2">
            {agents.map((agent) => (
                <label key={agent.id} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40">
                    <Checkbox
                        checked={selected.includes(agent.id)}
                        aria-label={agent.name}
                        onCheckedChange={(v) => onChange(v ? [...selected, agent.id] : selected.filter((id) => id !== agent.id))}
                    />
                    {agent.name} <span className="font-mono text-xs text-muted-foreground">{agent.number}</span>
                </label>
            ))}
        </div>
    );
}

function WorkflowSelect({ workflows, value, onChange, label }: { workflows: WorkflowSummaryResponse[]; value: string; onChange: (v: string) => void; label: string }) {
    return (
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger aria-label={label} className="w-full">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectItem value="none">Pas de débordement</SelectItem>
                {workflows.map((w) => (
                    <SelectItem key={w.id} value={String(w.id)}>
                        {w.name}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}

export function QueuesTab({
    queues,
    agents,
    workflows,
    aiEnabled,
    error,
    onChanged,
}: {
    queues: PbxQueue[];
    agents: PbxAgent[];
    workflows: WorkflowSummaryResponse[];
    aiEnabled: boolean;
    error?: string;
    onChanged: () => void;
}) {
    const [strategies, setStrategies] = useState<Record<string, string>>({});
    const [creating, setCreating] = useState(false);
    const [form, setForm] = useState<NewQueue>(EMPTY);
    const [overflowFor, setOverflowFor] = useState<{ queue: PbxQueue; workflow: string; after: number } | null>(null);
    const [membersFor, setMembersFor] = useState<{ queue: PbxQueue; selected: number[] } | null>(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        void strategiesApiV1PbxStrategiesGet().then((r) => setStrategies((r.data as Record<string, string>) ?? {}));
    }, []);

    const create = async () => {
        setBusy(true);
        const response = await createQueueApiV1PbxQueuesPost({
            body: {
                label: form.label,
                extension: form.extension,
                strategy: form.strategy,
                ring_seconds: form.ring_seconds,
                agent_ids: form.agent_ids,
                overflow_workflow_id: form.overflow === "none" ? null : Number(form.overflow),
                overflow_after_seconds: form.overflow_after_seconds,
            },
        });
        setBusy(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Création impossible"));
            return;
        }
        toast.success(`File « ${form.label} » créée sur le ${form.extension}`);
        setCreating(false);
        setForm(EMPTY);
        onChanged();
    };

    const saveOverflow = async () => {
        if (!overflowFor) return;
        setBusy(true);
        const response = await queueOverflowApiV1PbxQueuesQueueIdOverflowPut({
            path: { queue_id: overflowFor.queue.id },
            body: {
                workflow_id: overflowFor.workflow === "none" ? null : Number(overflowFor.workflow),
                after_seconds: overflowFor.after,
            },
        });
        setBusy(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Réglage impossible"));
            return;
        }
        toast.success(overflowFor.workflow === "none" ? "Débordement retiré" : "Débordement vers l'agent IA activé");
        setOverflowFor(null);
        onChanged();
    };

    const saveMembers = async () => {
        if (!membersFor) return;
        setBusy(true);
        const before = new Set(membersFor.queue.agent_ids ?? []);
        const after = new Set(membersFor.selected);
        const queue_id = membersFor.queue.id;
        for (const agent_id of after) {
            if (!before.has(agent_id)) await addQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdPut({ path: { queue_id, agent_id } });
        }
        for (const agent_id of before) {
            if (!after.has(agent_id)) await removeQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdDelete({ path: { queue_id, agent_id } });
        }
        setBusy(false);
        toast.success("Membres mis à jour");
        setMembersFor(null);
        onChanged();
    };

    return (
        <PageSection
            title="Files d'attente"
            actions={
                <Button onClick={() => setCreating(true)}>
                    <ListPlus /> Nouvelle file
                </Button>
            }
        >
            {error && <p className="mb-3 text-sm text-amber-400">Indisponible pour le moment : {error}</p>}
            {queues.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Aucune file d&apos;attente.</p>
            ) : (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>File</TableHead>
                            <TableHead>Numéro</TableHead>
                            <TableHead>Membres</TableHead>
                            <TableHead>Débordement</TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {queues.map((queue) => (
                            <TableRow key={queue.id} data-testid="pbx-queue">
                                <TableCell className="font-medium">{queue.name}</TableCell>
                                <TableCell className="font-mono text-sm">{queue.extensions.join(", ") || "—"}</TableCell>
                                <TableCell>{queue.members}</TableCell>
                                <TableCell>
                                    {queue.overflow ? (
                                        <Badge variant="secondary" className="gap-1">
                                            <Bot className="size-3" /> {queue.overflow.workflow_name ?? "Agent IA"}
                                            {queue.wait_time_threshold ? ` après ${queue.wait_time_threshold} s` : ""}
                                        </Badge>
                                    ) : (
                                        <span className="text-sm text-muted-foreground">—</span>
                                    )}
                                </TableCell>
                                <TableCell className="space-x-1 text-right">
                                    <Button variant="ghost" size="sm" onClick={() => setMembersFor({ queue, selected: queue.agent_ids ?? [] })}>
                                        <Users /> Membres
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        disabled={!aiEnabled}
                                        onClick={() =>
                                            setOverflowFor({
                                                queue,
                                                workflow: queue.overflow ? String(queue.overflow.workflow_id) : "none",
                                                after: queue.wait_time_threshold ?? 60,
                                            })
                                        }
                                    >
                                        <Bot /> Débordement IA
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="text-destructive"
                                        aria-label={`Supprimer la file ${queue.name}`}
                                        onClick={async () => {
                                            if (!window.confirm(`Supprimer la file « ${queue.name} » ?`)) return;
                                            const response = await deleteQueueApiV1PbxQueuesQueueIdDelete({ path: { queue_id: queue.id } });
                                            if (response.error) toast.error(detailFromError(response.error, "Suppression impossible"));
                                            else {
                                                toast.success("File supprimée");
                                                onChanged();
                                            }
                                        }}
                                    >
                                        <Trash2 />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}

            <Dialog open={creating} onOpenChange={setCreating}>
                <DialogContent className="sm:max-w-xl">
                    <DialogHeader>
                        <DialogTitle>Nouvelle file d&apos;attente</DialogTitle>
                        <DialogDescription>Les appels sont distribués aux agents connectés, selon la stratégie choisie.</DialogDescription>
                    </DialogHeader>
                    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        <div className="space-y-1">
                            <Label htmlFor="q-label">Nom</Label>
                            <Input id="q-label" placeholder="Service client" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="q-ext">Numéro interne</Label>
                            <Input id="q-ext" inputMode="numeric" placeholder="3005" value={form.extension} onChange={(e) => setForm({ ...form, extension: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label>Distribution des appels</Label>
                            <Select value={form.strategy} onValueChange={(v) => setForm({ ...form, strategy: v })}>
                                <SelectTrigger aria-label="Stratégie" className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {Object.entries(strategies).map(([key, label]) => (
                                        <SelectItem key={key} value={key}>
                                            {label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="q-ring">Sonnerie par agent (secondes)</Label>
                            <Input id="q-ring" type="number" min={5} max={120} value={form.ring_seconds} onChange={(e) => setForm({ ...form, ring_seconds: Number(e.target.value) })} />
                        </div>
                        <div className="space-y-1 sm:col-span-2">
                            <Label>Agents</Label>
                            <AgentPicker agents={agents} selected={form.agent_ids} onChange={(ids) => setForm({ ...form, agent_ids: ids })} />
                        </div>
                        {aiEnabled && (
                            <>
                                <div className="space-y-1">
                                    <Label>Si personne ne répond, un agent IA prend l&apos;appel</Label>
                                    <WorkflowSelect workflows={workflows} value={form.overflow} label="Agent IA de débordement" onChange={(v) => setForm({ ...form, overflow: v })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="q-after">Après (secondes d&apos;attente)</Label>
                                    <Input id="q-after" type="number" min={10} max={3600} value={form.overflow_after_seconds} disabled={form.overflow === "none"} onChange={(e) => setForm({ ...form, overflow_after_seconds: Number(e.target.value) })} />
                                </div>
                            </>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreating(false)}>
                            Annuler
                        </Button>
                        <Button onClick={create} disabled={busy || !form.label.trim() || !form.extension.trim()}>
                            Créer la file
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={overflowFor !== null} onOpenChange={(open) => !open && setOverflowFor(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Débordement de « {overflowFor?.queue.name} » vers un agent IA</DialogTitle>
                        <DialogDescription>
                            L&apos;agent IA décroche quand l&apos;attente dépasse le délai, quand personne ne répond ou
                            quand aucun agent n&apos;est connecté. Aucun client ne reste sans réponse.
                        </DialogDescription>
                    </DialogHeader>
                    {overflowFor && (
                        <div className="grid gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                                <Label>Agent IA</Label>
                                <WorkflowSelect workflows={workflows} value={overflowFor.workflow} label="Agent IA" onChange={(v) => setOverflowFor({ ...overflowFor, workflow: v })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="o-after">Après (secondes)</Label>
                                <Input id="o-after" type="number" min={10} max={3600} value={overflowFor.after} disabled={overflowFor.workflow === "none"} onChange={(e) => setOverflowFor({ ...overflowFor, after: Number(e.target.value) })} />
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setOverflowFor(null)}>
                            Annuler
                        </Button>
                        <Button onClick={saveOverflow} disabled={busy}>
                            Enregistrer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={membersFor !== null} onOpenChange={(open) => !open && setMembersFor(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Membres de « {membersFor?.queue.name} »</DialogTitle>
                        <DialogDescription>Les agents cochés reçoivent les appels de la file.</DialogDescription>
                    </DialogHeader>
                    {membersFor && (
                        <AgentPicker agents={agents} selected={membersFor.selected} onChange={(ids) => setMembersFor({ ...membersFor, selected: ids })} />
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setMembersFor(null)}>
                            Annuler
                        </Button>
                        <Button onClick={saveMembers} disabled={busy}>
                            Enregistrer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageSection>
    );
}

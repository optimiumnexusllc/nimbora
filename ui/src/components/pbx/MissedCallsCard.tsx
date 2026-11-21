"use client";

import { Bot } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { readMissedCallsApiV1PbxMissedCallsGet, saveMissedCallsApiV1PbxMissedCallsPut } from "@/client/sdk.gen";
import type { WorkflowSummaryResponse } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";

type Policy = {
    enabled: boolean;
    workflow_id: number | null;
    delay_minutes: number;
    scope: "queues" | "all";
    within_hours: boolean;
};

type RecentCallback = {
    id: number;
    phone: string;
    customer_name: string | null;
    reason: string | null;
    status: "pending" | "in_progress" | "done" | "failed" | "canceled";
    outcome: string | null;
    attempts: number;
    scheduled_at: string | null;
};

const STATUS: Record<RecentCallback["status"], { label: string; className: string }> = {
    pending: { label: "Prévu", className: "border-cyan-500/40 text-cyan-300" },
    in_progress: { label: "En cours", className: "border-violet-500/40 text-violet-300" },
    done: { label: "Rappelé", className: "border-emerald-500/40 text-emerald-300" },
    failed: { label: "Échec", className: "border-red-500/40 text-red-300" },
    canceled: { label: "Annulé", className: "text-muted-foreground" },
};

/**
 * Missed calls called back by an AI agent: who calls back, when, which calls,
 * and the latest automatic callbacks with their outcome.
 */
export function MissedCallsCard({ workflows }: { workflows: WorkflowSummaryResponse[] }) {
    const [policy, setPolicy] = useState<Policy | null>(null);
    const [recent, setRecent] = useState<RecentCallback[]>([]);
    const [saving, setSaving] = useState(false);

    const load = async () => {
        const response = await readMissedCallsApiV1PbxMissedCallsGet();
        if (response.error || !response.data) return;
        const data = response.data as unknown as { policy: Policy; recent: RecentCallback[] };
        setPolicy(data.policy);
        setRecent(data.recent);
    };

    useEffect(() => {
        void load();
    }, []);

    if (!policy) return null;
    const update = (fields: Partial<Policy>) => setPolicy({ ...policy, ...fields });

    const save = async () => {
        setSaving(true);
        const response = await saveMissedCallsApiV1PbxMissedCallsPut({ body: policy });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        toast.success(policy.enabled ? "Les appels manqués seront rappelés par l'agent IA" : "Rappel automatique désactivé");
        void load();
    };

    return (
        <PageSection
            title="Appels manqués rappelés par l'IA"
            description="Un client a raccroché avant qu'un conseiller ne décroche ? Un agent IA le rappelle, se présente au nom de l'entreprise et reprend sa demande. Si le client rappelle ou est rappelé par l'équipe entre-temps, le rappel est annulé."
        >
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="missed-calls">
                <div className="space-y-4">
                    <div className="flex items-center justify-between gap-4">
                        <Label htmlFor="missed-enabled">Rappeler automatiquement les appels manqués</Label>
                        <Switch
                            id="missed-enabled"
                            checked={policy.enabled}
                            onCheckedChange={(enabled) => update({ enabled })}
                        />
                    </div>
                    <div className="grid gap-1">
                        <Label>Agent IA qui rappelle</Label>
                        <Select
                            value={policy.workflow_id ? String(policy.workflow_id) : undefined}
                            onValueChange={(v) => update({ workflow_id: Number(v) })}
                        >
                            <SelectTrigger aria-label="Agent IA qui rappelle">
                                <SelectValue placeholder="Choisir un agent IA" />
                            </SelectTrigger>
                            <SelectContent>
                                {workflows.map((w) => (
                                    <SelectItem key={w.id} value={String(w.id)}>
                                        {w.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                            Il reçoit le motif (appel manqué, ou fiche de l&apos;IA si l&apos;appel lui avait été transféré)
                            dans son contexte : <code>callback_reason</code>, <code>customer_name</code>.
                        </p>
                    </div>
                    <div className="grid gap-2">
                        <Label>Quels appels</Label>
                        <RadioGroup value={policy.scope} onValueChange={(v) => update({ scope: v as Policy["scope"] })}>
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="queues" aria-label="Files d'attente seulement" />
                                Les clients qui ont raccroché dans une file d&apos;attente
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="all" aria-label="Tous les appels manqués" />
                                Tous les appels entrants sans réponse (postes, groupes, files)
                            </label>
                        </RadioGroup>
                    </div>
                    <div className="flex flex-wrap items-end gap-4">
                        <div className="grid gap-1">
                            <Label htmlFor="missed-delay">Rappeler après (minutes)</Label>
                            <Input
                                id="missed-delay"
                                type="number"
                                min={0}
                                max={1440}
                                className="w-32"
                                value={policy.delay_minutes}
                                onChange={(e) => update({ delay_minutes: Number(e.target.value) })}
                            />
                        </div>
                        <label className="flex items-center gap-2 pb-2 text-sm">
                            <Switch
                                checked={policy.within_hours}
                                onCheckedChange={(within_hours) => update({ within_hours })}
                                aria-label="Seulement pendant les heures d'ouverture"
                            />
                            Seulement pendant les heures d&apos;ouverture (Mon entreprise)
                        </label>
                    </div>
                    <Button onClick={save} disabled={saving}>
                        Enregistrer
                    </Button>
                </div>
                <div>
                    <Label className="mb-2 block">Derniers rappels automatiques</Label>
                    {recent.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Aucun pour l&apos;instant.</p>
                    ) : (
                        <ul className="divide-y divide-border/60 text-sm" data-testid="missed-callbacks">
                            {recent.map((c) => {
                                const status = STATUS[c.status] ?? STATUS.pending;
                                return (
                                    <li key={c.id} className="flex flex-wrap items-start gap-2 py-2">
                                        <Bot className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
                                        <span className="min-w-0 flex-1">
                                            <span className="font-medium">{c.customer_name || c.phone}</span>
                                            {c.customer_name && (
                                                <span className="ml-2 font-mono text-xs text-muted-foreground">{c.phone}</span>
                                            )}
                                            <span className="block text-xs text-muted-foreground">{c.outcome || c.reason}</span>
                                        </span>
                                        <span className="text-xs text-muted-foreground">
                                            {c.scheduled_at ? new Date(c.scheduled_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}
                                        </span>
                                        <Badge variant="outline" className={status.className}>
                                            {status.label}
                                        </Badge>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </div>
        </PageSection>
    );
}

"use client";

import { Send } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    readAlertsApiV1PbxSupervisionAlertsGet,
    saveAlertsApiV1PbxSupervisionAlertsPut,
    testAlertsApiV1PbxSupervisionAlertsTestPost,
} from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

import { formatDuration } from "./format";

export type AlertSettings = {
    enabled: boolean;
    max_wait_seconds: number;
    max_waiting: number;
    no_agent: boolean;
    queue_ids: number[];
    webhook_url: string;
    email_tool_uuid: string | null;
    email_recipients: string[];
    cooldown_minutes: number;
};

type LogEntry = {
    at: string;
    event: "alert" | "resolved";
    message?: string;
    level?: "critical" | "warning";
    duration_seconds?: number;
    channels?: Record<string, string>;
};

type State = { settings: AlertSettings; email_tools: { uuid: string; name: string }[]; log: LogEntry[] };

export function AlertsDialog({
    open,
    onOpenChange,
    queues,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    queues: { id: number; name: string }[];
}) {
    const [state, setState] = useState<State | null>(null);
    const [draft, setDraft] = useState<AlertSettings | null>(null);
    const [recipients, setRecipients] = useState("");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!open) return;
        void (async () => {
            const response = await readAlertsApiV1PbxSupervisionAlertsGet();
            if (response.error || !response.data) {
                toast.error(detailFromError(response.error, "Alertes indisponibles"));
                return;
            }
            const loaded = response.data as unknown as State;
            setState(loaded);
            setDraft(loaded.settings);
            setRecipients(loaded.settings.email_recipients.join("\n"));
        })();
    }, [open]);

    const update = (fields: Partial<AlertSettings>) => draft && setDraft({ ...draft, ...fields });

    const body = (): AlertSettings | null =>
        draft && {
            ...draft,
            email_recipients: recipients
                .split(/[\s,;]+/)
                .map((r) => r.trim())
                .filter(Boolean),
        };

    const save = async (): Promise<boolean> => {
        const payload = body();
        if (!payload) return false;
        setBusy(true);
        const response = await saveAlertsApiV1PbxSupervisionAlertsPut({ body: payload });
        setBusy(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return false;
        }
        return true;
    };

    const test = async () => {
        if (!(await save())) return;
        setBusy(true);
        const response = await testAlertsApiV1PbxSupervisionAlertsTestPost();
        setBusy(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Test impossible"));
            return;
        }
        const channels = (response.data as { channels: Record<string, string> }).channels;
        const failed = Object.entries(channels).filter(([, v]) => v !== "sent");
        if (failed.length) toast.error(`Échec : ${failed.map(([k, v]) => `${k} (${v})`).join(", ")}`);
        else toast.success("Message de test envoyé");
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle>Alertes de supervision</DialogTitle>
                    <DialogDescription>
                        Quand un client attend trop longtemps ou qu&apos;une file n&apos;a plus de conseiller, la console
                        s&apos;affiche en rouge — et les personnes qui ne la regardent pas sont prévenues.
                    </DialogDescription>
                </DialogHeader>
                {!draft || !state ? (
                    <p className="text-sm text-muted-foreground">Chargement…</p>
                ) : (
                    <Tabs defaultValue="rules">
                        <TabsList>
                            <TabsTrigger value="rules">Règles et canaux</TabsTrigger>
                            <TabsTrigger value="log">Journal ({state.log.length})</TabsTrigger>
                        </TabsList>
                        <TabsContent value="rules" className="space-y-5 pt-2">
                            <div className="flex items-center justify-between gap-4">
                                <Label htmlFor="alerts-enabled">Activer les alertes</Label>
                                <Switch
                                    id="alerts-enabled"
                                    checked={draft.enabled}
                                    onCheckedChange={(enabled) => update({ enabled })}
                                />
                            </div>
                            <div className="grid items-end gap-4 sm:grid-cols-3">
                                <div className="grid gap-1">
                                    <Label htmlFor="alert-wait">Attente maximale (s)</Label>
                                    <Input
                                        id="alert-wait"
                                        type="number"
                                        min={10}
                                        max={3600}
                                        value={draft.max_wait_seconds}
                                        onChange={(e) => update({ max_wait_seconds: Number(e.target.value) })}
                                    />
                                </div>
                                <div className="grid gap-1">
                                    <Label htmlFor="alert-waiting">Appelants en file (max.)</Label>
                                    <Input
                                        id="alert-waiting"
                                        type="number"
                                        min={1}
                                        max={200}
                                        value={draft.max_waiting}
                                        onChange={(e) => update({ max_waiting: Number(e.target.value) })}
                                    />
                                </div>
                                <div className="grid gap-1">
                                    <Label htmlFor="alert-cooldown">Délai entre envois (min)</Label>
                                    <Input
                                        id="alert-cooldown"
                                        type="number"
                                        min={1}
                                        max={1440}
                                        value={draft.cooldown_minutes}
                                        onChange={(e) => update({ cooldown_minutes: Number(e.target.value) })}
                                    />
                                </div>
                            </div>
                            <label className="flex items-center gap-2 text-sm">
                                <Checkbox
                                    checked={draft.no_agent}
                                    onCheckedChange={(checked) => update({ no_agent: Boolean(checked) })}
                                    aria-label="File sans conseiller"
                                />
                                Alerter quand des clients attendent et qu&apos;aucun conseiller de la file n&apos;est disponible
                            </label>
                            {queues.length > 0 && (
                                <div className="space-y-1">
                                    <Label>Files surveillées (aucune cochée : toutes)</Label>
                                    <div className="flex flex-wrap gap-3">
                                        {queues.map((q) => (
                                            <label key={q.id} className="flex items-center gap-2 text-sm">
                                                <Checkbox
                                                    checked={draft.queue_ids.includes(q.id)}
                                                    onCheckedChange={(checked) =>
                                                        update({
                                                            queue_ids: checked
                                                                ? [...draft.queue_ids, q.id]
                                                                : draft.queue_ids.filter((id) => id !== q.id),
                                                        })
                                                    }
                                                    aria-label={`Surveiller ${q.name}`}
                                                />
                                                {q.name}
                                            </label>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="grid gap-1">
                                <Label htmlFor="alert-webhook">Webhook (Slack, Teams, Google Chat, n8n…)</Label>
                                <Input
                                    id="alert-webhook"
                                    placeholder="https://hooks.slack.com/services/…"
                                    value={draft.webhook_url}
                                    onChange={(e) => update({ webhook_url: e.target.value })}
                                />
                                <p className="text-xs text-muted-foreground">
                                    Reçoit <code>{'{"text": …, "alert": {…}}'}</code> au début et à la fin de chaque alerte.
                                </p>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="grid min-w-0 gap-1">
                                    <Label>Envoyer les e-mails avec</Label>
                                    <Select
                                        value={draft.email_tool_uuid ?? undefined}
                                        onValueChange={(v) => update({ email_tool_uuid: v })}
                                    >
                                        <SelectTrigger aria-label="Outil e-mail" className="w-full min-w-0">
                                            <SelectValue
                                                placeholder={
                                                    state.email_tools.length
                                                        ? "Choisir un outil e-mail"
                                                        : "Aucun outil e-mail configuré"
                                                }
                                            />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {state.email_tools.map((t) => (
                                                <SelectItem key={t.uuid} value={t.uuid}>
                                                    {t.name}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <p className="text-xs text-muted-foreground">
                                        Un outil « Message » e-mail (SMTP) de vos agents, avec son expéditeur.
                                    </p>
                                </div>
                                <div className="grid min-w-0 gap-1">
                                    <Label htmlFor="alert-recipients">Destinataires</Label>
                                    <Textarea
                                        id="alert-recipients"
                                        rows={3}
                                        placeholder={"superviseur@entreprise.com\nresponsable@entreprise.com"}
                                        value={recipients}
                                        onChange={(e) => setRecipients(e.target.value)}
                                    />
                                </div>
                            </div>
                        </TabsContent>
                        <TabsContent value="log" className="pt-2">
                            {state.log.length === 0 ? (
                                <p className="text-sm text-muted-foreground">Aucune alerte envoyée pour l&apos;instant.</p>
                            ) : (
                                <ul className="max-h-80 divide-y divide-border/60 overflow-y-auto text-sm" data-testid="alerts-log">
                                    {state.log.map((entry, index) => (
                                        <li key={index} className="flex flex-wrap items-start gap-2 py-2">
                                            <span className="font-mono text-xs text-muted-foreground">
                                                {new Date(entry.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" })}
                                            </span>
                                            <span className="flex-1">
                                                {entry.event === "resolved" ? "✅ Rétabli — " : entry.level === "critical" ? "🔴 " : "🟠 "}
                                                {entry.message}
                                                {entry.event === "resolved" && entry.duration_seconds !== undefined && (
                                                    <span className="text-muted-foreground"> (après {formatDuration(entry.duration_seconds)})</span>
                                                )}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </TabsContent>
                    </Tabs>
                )}
                <DialogFooter className="gap-2">
                    <Button variant="outline" onClick={test} disabled={busy || !draft}>
                        <Send className="mr-1 h-4 w-4" /> Enregistrer et tester
                    </Button>
                    <Button
                        onClick={async () => {
                            if (await save()) {
                                toast.success("Alertes enregistrées");
                                onOpenChange(false);
                            }
                        }}
                        disabled={busy || !draft}
                    >
                        Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

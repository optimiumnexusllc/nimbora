"use client";

import {
    Bot,
    CalendarClock,
    Check,
    Headset,
    PhoneCall,
    PhoneMissed,
    PhoneOff,
    Plus,
    TimerReset,
    X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { getWorkflowsSummaryApiV1WorkflowSummaryGet } from "@/client/sdk.gen";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { type Callback, enterpriseApi, type Queue } from "@/lib/enterpriseApi";

const SOURCE_LABEL: Record<Callback["source"], string> = {
    ai_agent: "Demandé à l'agent IA",
    queue_timeout: "Appel sans réponse",
    manual: "Ajouté à la main",
    pbx_missed: "Appel manqué (PBX)",
};

const STATUS_LABEL: Record<Callback["status"], string> = {
    pending: "À rappeler",
    in_progress: "En cours",
    done: "Rappelé",
    failed: "Échec",
    canceled: "Annulé",
};

function errorText(e: unknown, fallback: string) {
    return e instanceof Error ? e.message : fallback;
}

/** Local "YYYY-MM-DDTHH:mm" for <input type="datetime-local">. */
function toLocalInput(date: Date) {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatWhen(iso: string, now = new Date()) {
    const date = new Date(iso);
    const minutes = Math.round((date.getTime() - now.getTime()) / 60000);
    const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    if (minutes <= 0) {
        const late = -minutes;
        if (late < 1) return "maintenant";
        if (late < 60) return `en retard de ${late} min`;
        if (late < 24 * 60) return `en retard de ${Math.floor(late / 60)} h`;
        return `depuis le ${date.toLocaleDateString("fr-FR")}`;
    }
    if (minutes < 60) return `dans ${minutes} min`;
    const sameDay = date.toDateString() === now.toDateString();
    if (sameDay) return `aujourd'hui à ${time}`;
    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);
    if (date.toDateString() === tomorrow.toDateString()) return `demain à ${time}`;
    return `${date.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })} à ${time}`;
}

function NewCallbackDialog({
    open,
    onClose,
    onCreated,
    queues,
    agents,
}: {
    open: boolean;
    onClose: () => void;
    onCreated: () => void;
    queues: Queue[];
    agents: { id: number; name: string }[];
}) {
    const [phone, setPhone] = useState("");
    const [name, setName] = useState("");
    const [reason, setReason] = useState("");
    const [when, setWhen] = useState(() => toLocalInput(new Date()));
    const [assignTo, setAssignTo] = useState<"human" | "ai">("human");
    const [queueSlug, setQueueSlug] = useState("any");
    const [workflowId, setWorkflowId] = useState<string>("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (open) {
            setPhone("");
            setName("");
            setReason("");
            setWhen(toLocalInput(new Date()));
            setAssignTo("human");
            setQueueSlug("any");
            setWorkflowId("");
        }
    }, [open]);

    const save = async () => {
        setSaving(true);
        try {
            await enterpriseApi.createCallback({
                phone,
                customer_name: name || null,
                reason: reason || null,
                scheduled_at: new Date(when).toISOString(),
                assign_to: assignTo,
                queue_slug: assignTo === "human" && queueSlug !== "any" ? queueSlug : null,
                workflow_id: assignTo === "ai" ? Number(workflowId) : null,
            });
            toast.success("Rappel planifié");
            onCreated();
            onClose();
        } catch (e) {
            toast.error(errorText(e, "Impossible de planifier ce rappel"));
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>Planifier un rappel</DialogTitle>
                    <DialogDescription>
                        Confiez-le à votre équipe ou à un agent IA, qui appellera automatiquement à l&apos;heure
                        prévue.
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4">
                    <div className="grid grid-cols-2 gap-3">
                        <div className="grid gap-1.5">
                            <Label htmlFor="cb-phone">Numéro</Label>
                            <Input
                                id="cb-phone"
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                placeholder="+227 90 12 34 56"
                            />
                        </div>
                        <div className="grid gap-1.5">
                            <Label htmlFor="cb-name">Client</Label>
                            <Input id="cb-name" value={name} onChange={(e) => setName(e.target.value)} />
                        </div>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="cb-reason">Motif</Label>
                        <Textarea
                            id="cb-reason"
                            rows={2}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="Ex. : envoyer le devis, confirmer le rendez-vous…"
                        />
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="cb-when">Quand</Label>
                        <Input id="cb-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
                    </div>
                    <div className="grid gap-1.5">
                        <Label>Qui rappelle</Label>
                        <div className="grid grid-cols-2 gap-2">
                            {(
                                [
                                    ["human", "Mon équipe", Headset],
                                    ["ai", "Un agent IA", Bot],
                                ] as const
                            ).map(([value, label, Icon]) => (
                                <button
                                    key={value}
                                    type="button"
                                    onClick={() => setAssignTo(value)}
                                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
                                        assignTo === value
                                            ? "border-primary bg-primary/10 text-foreground"
                                            : "border-border/60 text-muted-foreground hover:bg-accent/40"
                                    }`}
                                >
                                    <Icon className="h-4 w-4" />
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>
                    {assignTo === "human" ? (
                        <div className="grid gap-1.5">
                            <Label>File</Label>
                            <Select value={queueSlug} onValueChange={setQueueSlug}>
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="any">Toute l&apos;équipe</SelectItem>
                                    {queues.map((q) => (
                                        <SelectItem key={q.slug} value={q.slug}>
                                            {q.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    ) : (
                        <div className="grid gap-1.5">
                            <Label>Agent IA</Label>
                            <Select value={workflowId} onValueChange={setWorkflowId}>
                                <SelectTrigger className="w-full">
                                    <SelectValue placeholder="Choisir l'agent qui appellera" />
                                </SelectTrigger>
                                <SelectContent>
                                    {agents.map((a) => (
                                        <SelectItem key={a.id} value={String(a.id)}>
                                            {a.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                </div>
                <DialogFooter>
                    <Button variant="ghost" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button
                        onClick={save}
                        disabled={saving || phone.trim().length < 3 || (assignTo === "ai" && !workflowId)}
                    >
                        Planifier
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function CallbackRow({
    callback,
    canDial,
    agentName,
    onChanged,
}: {
    callback: Callback;
    canDial: boolean;
    agentName: (id: number | null) => string | null;
    onChanged: () => void;
}) {
    const [busy, setBusy] = useState(false);
    const [rescheduling, setRescheduling] = useState(false);
    const [when, setWhen] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60000)));
    const overdue = callback.status === "pending" && new Date(callback.scheduled_at) <= new Date();
    const open = callback.status === "pending" || callback.status === "in_progress";

    const act = async (fn: () => Promise<unknown>, success?: string) => {
        setBusy(true);
        try {
            await fn();
            if (success) toast.success(success);
            onChanged();
        } catch (e) {
            toast.error(errorText(e, "Action impossible"));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            data-testid="callback-row"
            className={`rounded-xl border p-4 transition ${
                overdue ? "border-amber-500/50 bg-amber-500/5" : "border-border/60 bg-card/40"
            }`}
        >
            <div className="flex flex-wrap items-start gap-3">
                <div
                    className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                        callback.assign_to === "ai" ? "bg-violet-500/15 text-violet-400" : "bg-cyan-500/15 text-cyan-400"
                    }`}
                >
                    {callback.assign_to === "ai" ? <Bot className="h-4 w-4" /> : <Headset className="h-4 w-4" />}
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{callback.customer_name || callback.phone}</span>
                        {callback.customer_name && (
                            <span className="font-mono text-xs text-muted-foreground">{callback.phone}</span>
                        )}
                        <Badge variant="secondary">{SOURCE_LABEL[callback.source]}</Badge>
                        {callback.queue_slug && <Badge variant="outline">{callback.queue_slug}</Badge>}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{callback.reason || "Motif non précisé"}</p>
                    {callback.notes && (
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground/80">{callback.notes}</p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span className={`flex items-center gap-1 ${overdue ? "font-medium text-amber-400" : ""}`}>
                            <CalendarClock className="h-3.5 w-3.5" />
                            {open
                                ? formatWhen(callback.scheduled_at)
                                : callback.completed_at
                                  ? new Date(callback.completed_at).toLocaleString("fr-FR")
                                  : ""}
                        </span>
                        <span>
                            Tentative {callback.attempts}/{callback.max_attempts}
                        </span>
                        {callback.status === "in_progress" && agentName(callback.assigned_agent_id) && (
                            <span>Pris par {agentName(callback.assigned_agent_id)}</span>
                        )}
                        {callback.outcome && <span>· {callback.outcome}</span>}
                    </div>
                </div>
                <Badge
                    variant={
                        callback.status === "done" ? "default" : callback.status === "failed" ? "destructive" : "secondary"
                    }
                >
                    {STATUS_LABEL[callback.status]}
                </Badge>
            </div>

            {open && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
                    {callback.assign_to === "human" && callback.status === "pending" && (
                        <Button
                            size="sm"
                            disabled={busy || !canDial}
                            title={canDial ? undefined : "Reliez un poste de softphone à votre compte pour appeler"}
                            onClick={() =>
                                act(
                                    () => enterpriseApi.dialCallback(callback.id),
                                    "Votre softphone sonne : décrochez, le client sera appelé.",
                                )
                            }
                        >
                            <PhoneCall className="mr-1 h-4 w-4" />
                            Appeler
                        </Button>
                    )}
                    {callback.assign_to === "human" && callback.status === "in_progress" && (
                        <>
                            <Button
                                size="sm"
                                disabled={busy}
                                onClick={() =>
                                    act(
                                        () => enterpriseApi.completeCallback(callback.id, { result: "reached" }),
                                        "Rappel terminé",
                                    )
                                }
                            >
                                <Check className="mr-1 h-4 w-4" />
                                Client joint
                            </Button>
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() =>
                                    act(() =>
                                        enterpriseApi.completeCallback(callback.id, {
                                            result: "no_answer",
                                            retry_in_minutes: 60,
                                        }),
                                    )
                                }
                            >
                                <PhoneMissed className="mr-1 h-4 w-4" />
                                Pas de réponse
                            </Button>
                            <Button
                                size="sm"
                                variant="ghost"
                                disabled={busy}
                                onClick={() =>
                                    act(() => enterpriseApi.completeCallback(callback.id, { result: "wrong_number" }))
                                }
                            >
                                <PhoneOff className="mr-1 h-4 w-4" />
                                Mauvais numéro
                            </Button>
                        </>
                    )}
                    {callback.assign_to === "ai" && callback.status === "pending" && (
                        <span className="flex items-center gap-1.5 text-xs text-violet-300">
                            <Bot className="h-3.5 w-3.5" />
                            Appel automatique par l&apos;agent IA à l&apos;heure prévue
                        </span>
                    )}
                    {callback.status === "pending" &&
                        (rescheduling ? (
                            <span className="flex items-center gap-2">
                                <Input
                                    type="datetime-local"
                                    className="h-8 w-auto"
                                    value={when}
                                    onChange={(e) => setWhen(e.target.value)}
                                />
                                <Button
                                    size="sm"
                                    disabled={busy}
                                    onClick={() =>
                                        act(async () => {
                                            await enterpriseApi.updateCallback(callback.id, {
                                                scheduled_at: new Date(when).toISOString(),
                                            });
                                            setRescheduling(false);
                                        }, "Rappel reprogrammé")
                                    }
                                >
                                    OK
                                </Button>
                            </span>
                        ) : (
                            <Button size="sm" variant="outline" onClick={() => setRescheduling(true)}>
                                <TimerReset className="mr-1 h-4 w-4" />
                                Reprogrammer
                            </Button>
                        ))}
                    <Button
                        size="sm"
                        variant="ghost"
                        className="ml-auto text-muted-foreground"
                        disabled={busy}
                        onClick={() =>
                            act(() => enterpriseApi.updateCallback(callback.id, { status: "canceled" }), "Rappel annulé")
                        }
                    >
                        <X className="mr-1 h-4 w-4" />
                        Annuler
                    </Button>
                </div>
            )}
        </div>
    );
}

export function CallbacksPanel({
    queues,
    seatId,
    agentNames,
}: {
    queues: Queue[];
    seatId: number | null;
    agentNames: Record<number, string>;
}) {
    const [view, setView] = useState<"open" | "closed">("open");
    const [callbacks, setCallbacks] = useState<Callback[] | null>(null);
    const [creating, setCreating] = useState(false);
    const [aiAgents, setAiAgents] = useState<{ id: number; name: string }[]>([]);

    const load = useCallback(async () => {
        try {
            setCallbacks(await enterpriseApi.listCallbacks(view));
        } catch (e) {
            toast.error(errorText(e, "Chargement des rappels impossible"));
            setCallbacks([]);
        }
    }, [view]);

    useEffect(() => {
        void load();
        const timer = window.setInterval(() => void load(), 30000);
        return () => window.clearInterval(timer);
    }, [load]);

    useEffect(() => {
        getWorkflowsSummaryApiV1WorkflowSummaryGet({})
            .then((r) => {
                if (r.error || !r.data) return;
                setAiAgents(r.data.map((w) => ({ id: w.id, name: w.name })));
            })
            .catch(() => undefined);
    }, []);

    const stats = useMemo(() => {
        const list = callbacks ?? [];
        const now = new Date();
        return {
            overdue: list.filter((c) => c.status === "pending" && new Date(c.scheduled_at) <= now).length,
            ai: list.filter((c) => c.assign_to === "ai").length,
            human: list.filter((c) => c.assign_to === "human").length,
        };
    }, [callbacks]);

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
                <Tabs value={view} onValueChange={(v) => setView(v as "open" | "closed")}>
                    <TabsList>
                        <TabsTrigger value="open">À faire</TabsTrigger>
                        <TabsTrigger value="closed">Historique</TabsTrigger>
                    </TabsList>
                </Tabs>
                {view === "open" && callbacks && callbacks.length > 0 && (
                    <div className="flex flex-wrap gap-2 text-xs">
                        {stats.overdue > 0 && (
                            <Badge className="border-amber-500/40 bg-amber-500/15 text-amber-300">
                                {stats.overdue} à rappeler maintenant
                            </Badge>
                        )}
                        <Badge variant="secondary">
                            <Headset className="mr-1 h-3 w-3" />
                            {stats.human} équipe
                        </Badge>
                        <Badge variant="secondary">
                            <Bot className="mr-1 h-3 w-3" />
                            {stats.ai} IA
                        </Badge>
                    </div>
                )}
                <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
                    <Plus className="mr-1 h-4 w-4" />
                    Planifier un rappel
                </Button>
            </div>

            {callbacks === null ? null : callbacks.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                    {view === "open"
                        ? "Aucun rappel en attente. Les clients qui demandent à être rappelés, et ceux qui raccrochent avant qu'un conseiller ne réponde, apparaîtront ici."
                        : "Aucun rappel terminé pour l'instant."}
                </p>
            ) : (
                <div className="grid gap-3">
                    {callbacks.map((c) => (
                        <CallbackRow
                            key={c.id}
                            callback={c}
                            canDial={seatId !== null}
                            agentName={(id) => (id ? (agentNames[id] ?? null) : null)}
                            onChanged={load}
                        />
                    ))}
                </div>
            )}

            <NewCallbackDialog
                open={creating}
                onClose={() => setCreating(false)}
                onCreated={load}
                queues={queues}
                agents={aiAgents}
            />
        </div>
    );
}

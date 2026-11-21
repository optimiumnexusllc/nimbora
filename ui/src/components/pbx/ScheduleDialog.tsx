"use client";

import { Clock } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { listVoicemailsApiV1PbxVoicemailsGet, syncScheduleApiV1PbxSchedulePut } from "@/client/sdk.gen";
import type { WorkflowSummaryResponse } from "@/client/types.gen";
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
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";

import type { PbxNumber } from "./types";

type Closed = "ai_agent" | "voicemail" | "hangup";

/** Opening hours of "Mon entreprise" → PBX numbers; outside hours → AI agent. */
export function ScheduleDialog({
    open,
    onOpenChange,
    numbers,
    workflows,
    aiEnabled,
    onDone,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    numbers: PbxNumber[];
    workflows: WorkflowSummaryResponse[];
    aiEnabled: boolean;
    onDone: () => void;
}) {
    const humanNumbers = numbers.filter((n) => !n.ai_workflow_id);
    const [selected, setSelected] = useState<number[]>([]);
    const [closed, setClosed] = useState<Closed>(aiEnabled ? "ai_agent" : "voicemail");
    const [workflowId, setWorkflowId] = useState("");
    const [voicemails, setVoicemails] = useState<{ id: number; name: string; number: string }[]>([]);
    const [voicemailId, setVoicemailId] = useState("");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!open) return;
        setSelected(humanNumbers.map((n) => n.incall_id));
        void listVoicemailsApiV1PbxVoicemailsGet().then((r) => setVoicemails((r.data as typeof voicemails) ?? []));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open]);

    const ready =
        selected.length > 0 &&
        (closed === "hangup" || (closed === "ai_agent" && workflowId) || (closed === "voicemail" && voicemailId));

    const apply = async () => {
        setBusy(true);
        const response = await syncScheduleApiV1PbxSchedulePut({
            body: {
                incall_ids: [...new Set(selected)],
                closed,
                workflow_id: closed === "ai_agent" ? Number(workflowId) : null,
                voicemail_id: closed === "voicemail" ? Number(voicemailId) : null,
            },
        });
        setBusy(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Application impossible"));
            return;
        }
        const data = response.data as { open_periods: number; closures: number };
        toast.success(`Horaires appliqués : ${data.open_periods} plage(s), ${data.closures} fermeture(s)`);
        onOpenChange(false);
        onDone();
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader className="min-w-0">
                    <DialogTitle className="flex items-center gap-2">
                        <Clock className="size-5" /> Horaires d&apos;ouverture des numéros
                    </DialogTitle>
                    <DialogDescription>
                        Les horaires et fermetures exceptionnelles de{" "}
                        <Link href="/business" className="underline">
                            Mon entreprise
                        </Link>{" "}
                        s&apos;appliquent aux numéros choisis. Modifiez-les là-bas puis réappliquez : une seule source.
                    </DialogDescription>
                </DialogHeader>
                <div className="min-w-0 space-y-4">
                    <div className="space-y-1">
                        <Label>Numéros concernés</Label>
                        {humanNumbers.length === 0 ? (
                            <p className="text-sm text-muted-foreground">Aucun numéro routé vers vos équipes.</p>
                        ) : (
                            <div className="grid gap-1 rounded-md border border-border/60 p-2">
                                {humanNumbers.map((n) => (
                                    <label key={`${n.incall_id}-${n.number}`} className="flex items-center gap-2 text-sm">
                                        <Checkbox
                                            aria-label={n.number}
                                            checked={selected.includes(n.incall_id)}
                                            onCheckedChange={(v) =>
                                                setSelected(v ? [...selected, n.incall_id] : selected.filter((id) => id !== n.incall_id))
                                            }
                                        />
                                        <span className="font-mono">{n.number}</span>
                                        <span className="text-muted-foreground">→ {n.destination}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>
                    <div className="space-y-2">
                        <Label>En dehors des horaires</Label>
                        <RadioGroup value={closed} onValueChange={(v) => setClosed(v as Closed)} className="space-y-1">
                            {aiEnabled && (
                                <label className="flex items-center gap-2 text-sm">
                                    <RadioGroupItem value="ai_agent" aria-label="Un agent IA répond" /> Un agent IA répond (recommandé)
                                </label>
                            )}
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="voicemail" aria-label="Messagerie" /> Messagerie vocale
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="hangup" aria-label="Raccrocher" /> Raccrocher
                            </label>
                        </RadioGroup>
                        {closed === "ai_agent" && (
                            <Select value={workflowId} onValueChange={setWorkflowId}>
                                <SelectTrigger aria-label="Agent IA hors horaires" className="w-full">
                                    <SelectValue placeholder="Choisir l'agent IA" />
                                </SelectTrigger>
                                <SelectContent>
                                    {workflows.map((w) => (
                                        <SelectItem key={w.id} value={String(w.id)}>
                                            {w.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}
                        {closed === "voicemail" && (
                            <Select value={voicemailId} onValueChange={setVoicemailId}>
                                <SelectTrigger aria-label="Messagerie hors horaires" className="w-full">
                                    <SelectValue placeholder="Choisir la messagerie" />
                                </SelectTrigger>
                                <SelectContent>
                                    {voicemails.map((v) => (
                                        <SelectItem key={v.id} value={String(v.id)}>
                                            {v.name} ({v.number})
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button onClick={apply} disabled={busy || !ready}>
                        Appliquer les horaires
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

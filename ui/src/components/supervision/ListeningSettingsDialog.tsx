"use client";

import { ScrollText, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { listSessionsApiV1PbxSupervisionSessionsGet, saveSettingsApiV1PbxSupervisionSettingsPut } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { detailFromError } from "@/lib/apiError";

import type { Extension } from "./PbxSupervision";
import type { ListeningSettings, SpyMode } from "./types";
import { SPY_LABELS } from "./types";

type Session = {
    id: number;
    mode: SpyMode;
    supervisor_name: string | null;
    target_name: string | null;
    target_extension: string | null;
    created_at: string | null;
};

const MODE_HELP: Record<SpyMode, string> = {
    listen: "personne ne vous entend",
    whisper: "seul le conseiller vous entend",
    barge: "le client et le conseiller vous entendent",
};

function ExtensionChecklist({
    label,
    hint,
    extensions,
    selected,
    onChange,
    testId,
}: {
    label: string;
    hint: string;
    extensions: Extension[];
    selected: string[];
    onChange: (next: string[]) => void;
    testId: string;
}) {
    return (
        <div className="space-y-2" data-testid={testId}>
            <div>
                <Label>{label}</Label>
                <p className="text-xs text-muted-foreground">{hint}</p>
            </div>
            <div className="grid max-h-40 gap-1 overflow-y-auto rounded-md border border-border/60 p-2 sm:grid-cols-2">
                {extensions.map((e) => (
                    <label key={e.uuid} className="flex items-center gap-2 text-sm">
                        <Checkbox
                            checked={selected.includes(e.uuid)}
                            onCheckedChange={(checked) =>
                                onChange(checked ? [...selected, e.uuid] : selected.filter((u) => u !== e.uuid))
                            }
                            aria-label={`${label} : ${e.name}`}
                        />
                        <span className="font-mono text-xs text-muted-foreground">{e.extension}</span>
                        {e.name}
                    </label>
                ))}
            </div>
        </div>
    );
}

export function ListeningSettingsDialog({
    open,
    onOpenChange,
    settings,
    extensions,
    onSaved,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    settings: ListeningSettings | null;
    extensions: Extension[];
    onSaved: (settings: ListeningSettings) => void;
}) {
    const [draft, setDraft] = useState<ListeningSettings | null>(settings);
    const [saving, setSaving] = useState(false);
    const [sessions, setSessions] = useState<Session[] | null>(null);

    useEffect(() => {
        if (open) setDraft(settings);
    }, [open, settings]);

    const loadSessions = async () => {
        const response = await listSessionsApiV1PbxSupervisionSessionsGet();
        if (response.error) {
            toast.error(detailFromError(response.error, "Journal indisponible"));
            setSessions([]);
            return;
        }
        setSessions(((response.data as { sessions?: Session[] })?.sessions ?? []) as Session[]);
    };

    if (!draft) return null;
    const update = (fields: Partial<ListeningSettings>) => setDraft({ ...draft, ...fields });

    const save = async () => {
        setSaving(true);
        const response = await saveSettingsApiV1PbxSupervisionSettingsPut({
            body: {
                enabled: draft.enabled,
                modes: draft.modes,
                supervisors: draft.supervisors,
                protected: draft.protected,
                notice_acknowledged: draft.notice_acknowledged,
                sla_seconds: draft.sla_seconds,
            },
        });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        toast.success("Réglages de l'écoute enregistrés");
        onSaved({ ...draft, ...(response.data as ListeningSettings) });
        onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle>Écoute des appels et qualité de service</DialogTitle>
                    <DialogDescription>
                        Écouter, chuchoter ou intervenir sur les appels des conseillers depuis la supervision. Votre téléphone
                        sonne, vous décrochez : vous êtes dans l&apos;appel.
                    </DialogDescription>
                </DialogHeader>
                <Tabs defaultValue="settings" onValueChange={(tab) => tab === "journal" && void loadSessions()}>
                    <TabsList>
                        <TabsTrigger value="settings">Réglages</TabsTrigger>
                        <TabsTrigger value="journal">
                            <ScrollText className="mr-1 h-4 w-4" />
                            Journal des écoutes
                        </TabsTrigger>
                    </TabsList>
                    <TabsContent value="settings" className="space-y-5 pt-2">
                        <label className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                            <Checkbox
                                checked={draft.notice_acknowledged}
                                onCheckedChange={(checked) => update({ notice_acknowledged: Boolean(checked) })}
                                aria-label="Collaborateurs informés"
                            />
                            <span>
                                <span className="flex items-center gap-1 font-medium">
                                    <ShieldCheck className="h-4 w-4 text-amber-400" />
                                    Les collaborateurs ont été informés de l&apos;écoute de leurs appels
                                </span>
                                <span className="text-xs text-muted-foreground">
                                    Le droit du travail et la protection des données l&apos;exigent généralement
                                    (information préalable, finalité de formation ou de qualité, représentants du personnel
                                    consultés). Annoncez aussi l&apos;écoute aux appelants si la loi applicable le demande.
                                </span>
                            </span>
                        </label>
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <Label htmlFor="listening-enabled">Activer l&apos;écoute des appels</Label>
                                <p className="text-xs text-muted-foreground">
                                    Désactivée par défaut. Chaque écoute est inscrite au journal : qui a écouté qui, quand et comment.
                                </p>
                            </div>
                            <Switch
                                id="listening-enabled"
                                checked={draft.enabled}
                                onCheckedChange={(checked) => update({ enabled: checked })}
                                disabled={!draft.notice_acknowledged && !draft.enabled}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Modes autorisés</Label>
                            <div className="grid gap-2 sm:grid-cols-3">
                                {(Object.keys(SPY_LABELS) as SpyMode[]).map((mode) => (
                                    <label key={mode} className="flex items-start gap-2 rounded-md border border-border/60 p-2 text-sm">
                                        <Checkbox
                                            checked={draft.modes.includes(mode)}
                                            onCheckedChange={(checked) =>
                                                update({
                                                    modes: checked
                                                        ? [...draft.modes, mode]
                                                        : draft.modes.filter((m) => m !== mode),
                                                })
                                            }
                                            aria-label={SPY_LABELS[mode]}
                                        />
                                        <span>
                                            {SPY_LABELS[mode]}
                                            <span className="block text-xs text-muted-foreground">{MODE_HELP[mode]}</span>
                                        </span>
                                    </label>
                                ))}
                            </div>
                        </div>
                        <ExtensionChecklist
                            testId="listening-supervisors"
                            label="Postes superviseurs"
                            hint="Seuls ces postes peuvent écouter. Aucun coché : tous les postes."
                            extensions={extensions}
                            selected={draft.supervisors}
                            onChange={(supervisors) => update({ supervisors })}
                        />
                        <ExtensionChecklist
                            testId="listening-protected"
                            label="Postes jamais écoutés"
                            hint="Direction, ressources humaines, représentants du personnel…"
                            extensions={extensions}
                            selected={draft.protected}
                            onChange={(list) => update({ protected: list })}
                        />
                        <div className="grid gap-1 sm:max-w-xs">
                            <Label htmlFor="sla-seconds">Seuil de qualité de service (secondes)</Label>
                            <Input
                                id="sla-seconds"
                                type="number"
                                min={5}
                                max={600}
                                value={draft.sla_seconds}
                                onChange={(e) => update({ sla_seconds: Number(e.target.value) })}
                            />
                            <p className="text-xs text-muted-foreground">
                                Un appel décroché avant ce délai compte dans le niveau de service ; au-delà, l&apos;attente
                                passe en rouge.
                            </p>
                        </div>
                    </TabsContent>
                    <TabsContent value="journal" className="pt-2">
                        {sessions === null ? (
                            <p className="text-sm text-muted-foreground">Chargement…</p>
                        ) : sessions.length === 0 ? (
                            <p className="text-sm text-muted-foreground">Aucune écoute pour l&apos;instant.</p>
                        ) : (
                            <ul className="max-h-80 divide-y divide-border/60 overflow-y-auto text-sm" data-testid="listening-journal">
                                {sessions.map((s) => (
                                    <li key={s.id} className="flex flex-wrap items-center gap-2 py-2">
                                        <span className="font-mono text-xs text-muted-foreground">
                                            {s.created_at ? new Date(s.created_at).toLocaleString("fr-FR") : "—"}
                                        </span>
                                        <span>
                                            <strong>{s.supervisor_name || "Superviseur"}</strong> ·{" "}
                                            {SPY_LABELS[s.mode]?.toLowerCase() ?? s.mode} ·{" "}
                                            <strong>{s.target_name || "poste"}</strong>
                                            {s.target_extension ? ` (${s.target_extension})` : ""}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </TabsContent>
                </Tabs>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button onClick={save} disabled={saving}>
                        Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

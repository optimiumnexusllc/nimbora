"use client";

import { BellOff, Bot, Loader2, PhoneForwarded } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    readCallSettingsApiV1PbxExtensionsUserIdCallSettingsGet,
    saveCallSettingsApiV1PbxExtensionsUserIdCallSettingsPut,
} from "@/client/sdk.gen";
import type { MenuAction } from "@/client/types.gen";
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
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";

import { type Destination, DestinationPicker,type DestinationSources } from "./DestinationPicker";
import type { PbxUser } from "./types";

type Forward = { enabled: boolean; destination: string };
type Kind = "unconditional" | "busy" | "noanswer";
type Settings = {
    user_id: number;
    name: string;
    forwards: Record<Kind, Forward>;
    dnd: boolean;
    unanswered: (Destination & { workflow_name?: string | null }) | null;
};

const KINDS: { kind: Kind; label: string; hint: string }[] = [
    { kind: "unconditional", label: "Toujours", hint: "Tous les appels partent vers ce numéro" },
    { kind: "busy", label: "Si occupé", hint: "Quand le poste est déjà en ligne" },
    { kind: "noanswer", label: "Si pas de réponse", hint: "Après la sonnerie du poste" },
];
const NONE: Destination = { type: "hangup", target_id: null };

export function CallSettingsDialog({
    user,
    onClose,
    sources,
}: {
    user: PbxUser | null;
    onClose: () => void;
    sources: DestinationSources;
}) {
    const [settings, setSettings] = useState<Settings | null>(null);
    const [unanswered, setUnanswered] = useState<Destination>(NONE);
    const [handle, setHandle] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setSettings(null);
        if (!user?.id) return;
        void (async () => {
            const response = await readCallSettingsApiV1PbxExtensionsUserIdCallSettingsGet({ path: { user_id: user.id as number } });
            if (response.error || !response.data) {
                toast.error(detailFromError(response.error, "Chargement impossible"));
                onClose();
                return;
            }
            const data = response.data as unknown as Settings;
            setSettings(data);
            setHandle(Boolean(data.unanswered));
            setUnanswered(data.unanswered ? { type: data.unanswered.type, target_id: data.unanswered.target_id } : sources.aiEnabled && sources.workflows[0] ? { type: "ai", target_id: sources.workflows[0].id } : { type: "voicemail", target_id: sources.voicemails[0]?.id ?? null });
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user?.id]);

    const setForward = (kind: Kind, patch: Partial<Forward>) =>
        setSettings((s) => (s ? { ...s, forwards: { ...s.forwards, [kind]: { ...s.forwards[kind], ...patch } } } : s));
    const missing = settings && KINDS.find(({ kind }) => settings.forwards[kind].enabled && !settings.forwards[kind].destination.trim());

    return (
        <Dialog open={user !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-2xl">
                <DialogHeader>
                    <DialogTitle>Renvois de {user?.name}</DialogTitle>
                    <DialogDescription>
                        Où vont les appels de ce poste : renvois vers un autre numéro, ne pas déranger, et ce qui se passe
                        quand personne ne décroche.
                    </DialogDescription>
                </DialogHeader>
                {!settings ? (
                    <div className="flex justify-center py-10">
                        <Loader2 className="animate-spin text-muted-foreground" />
                    </div>
                ) : (
                    <div className="space-y-4" data-testid="call-settings">
                        <label className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3">
                            <span className="text-sm">
                                <span className="flex items-center gap-1.5 font-medium">
                                    <BellOff className="size-4" /> Ne pas déranger
                                </span>
                                <span className="text-muted-foreground">Le poste ne sonne plus ; les appels suivent la règle « personne ne décroche ».</span>
                            </span>
                            <Switch aria-label="Ne pas déranger" checked={settings.dnd} onCheckedChange={(dnd) => setSettings({ ...settings, dnd })} />
                        </label>
                        <div className="space-y-2">
                            <Label className="flex items-center gap-1.5">
                                <PhoneForwarded className="size-4" /> Renvois
                            </Label>
                            {KINDS.map(({ kind, label, hint }) => (
                                <div key={kind} className="grid items-center gap-3 sm:grid-cols-[44px_150px_minmax(0,1fr)]">
                                    <Switch
                                        aria-label={`Renvoi ${label.toLowerCase()}`}
                                        checked={settings.forwards[kind].enabled}
                                        onCheckedChange={(enabled) => setForward(kind, { enabled })}
                                    />
                                    <span className="text-sm">
                                        {label}
                                        <span className="block text-xs text-muted-foreground">{hint}</span>
                                    </span>
                                    <Input
                                        aria-label={`Numéro du renvoi ${label.toLowerCase()}`}
                                        placeholder="+225 07 … ou 1002"
                                        disabled={!settings.forwards[kind].enabled}
                                        value={settings.forwards[kind].destination}
                                        onChange={(e) => setForward(kind, { destination: e.target.value })}
                                    />
                                </div>
                            ))}
                        </div>
                        <div className="space-y-2 rounded-lg border border-border/60 p-3">
                            <label className="flex items-center justify-between gap-3">
                                <span className="text-sm">
                                    <span className="flex items-center gap-1.5 font-medium">
                                        <Bot className="size-4 text-brand-cyan" /> Quand personne ne décroche
                                    </span>
                                    <span className="text-muted-foreground">Pas de réponse, occupé ou injoignable.</span>
                                </span>
                                <Switch aria-label="Rediriger les appels sans réponse" checked={handle} onCheckedChange={setHandle} />
                            </label>
                            {handle && (
                                <DestinationPicker
                                    label="Destination sans réponse"
                                    value={unanswered}
                                    sources={sources}
                                    allowed={["ai", "voicemail", "queue", "group", "user", "menu"]}
                                    onChange={setUnanswered}
                                />
                            )}
                            {handle && unanswered.type === "ai" && (
                                <p className="text-xs text-muted-foreground">
                                    L&apos;agent IA décroche à la place de {settings.name || "ce poste"}, répond aux questions et prend le message.
                                </p>
                            )}
                        </div>
                    </div>
                )}
                <DialogFooter className="items-center">
                    {missing && <p className="mr-auto text-sm text-amber-400">Renvoi « {missing.label} » : indiquez le numéro.</p>}
                    <Button variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button
                        disabled={!settings || Boolean(missing) || saving || (handle && unanswered.type !== "hangup" && unanswered.target_id == null)}
                        onClick={async () => {
                            if (!settings || !user?.id) return;
                            setSaving(true);
                            const response = await saveCallSettingsApiV1PbxExtensionsUserIdCallSettingsPut({
                                path: { user_id: user.id },
                                body: {
                                    ...settings.forwards,
                                    dnd: settings.dnd,
                                    unanswered: handle ? (unanswered as MenuAction) : null,
                                    unanswered_mode: "set",
                                },
                            });
                            setSaving(false);
                            if (response.error) {
                                toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                return;
                            }
                            toast.success(`Renvois de ${user.name} enregistrés`);
                            onClose();
                        }}
                    >
                        Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

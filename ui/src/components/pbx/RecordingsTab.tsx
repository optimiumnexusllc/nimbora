"use client";

import { ChevronDown, ChevronUp, CircleCheck, Disc3, FileText, Loader2, Play, RefreshCw, Save, Search, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    deleteRecordingApiV1PbxRecordingsRecordingIdDelete,
    listRecordingsApiV1PbxRecordingsGet,
    recordingAudioApiV1PbxRecordingsRecordingIdAudioGet,
    saveRecordingPolicyApiV1PbxRecordingsPolicyPut,
    syncRecordingsApiV1PbxRecordingsSyncPost,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";

import { DIRECTION_LABELS, type PbxUser } from "./types";

export type RecordingPolicy = {
    incoming_external: boolean;
    outgoing_external: boolean;
    internal: boolean;
    user_uuids: string[] | null;
    import_enabled: boolean;
    transcribe: boolean;
    remove_from_pbx: boolean;
};
export type PbxRecording = {
    id: number;
    started_at: string | null;
    duration_seconds: number | null;
    direction: string | null;
    source: string | null;
    source_name: string | null;
    destination: string | null;
    destination_name: string | null;
    customer_phone: string | null;
    size_bytes: number | null;
    transcript: string | null;
    transcript_status: string;
    removed_from_pbx: boolean;
};

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const duration = (s: number | null) => (s ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s` : "—");
const TRANSCRIPT: Record<string, string> = {
    failed: "Transcription en échec",
    unavailable: "Transcription non prise en charge par la reconnaissance vocale choisie",
};

function party(name: string | null, number: string | null) {
    return name ? `${name}${number && number !== name ? ` (${number})` : ""}` : (number ?? "—");
}

export function RecordingsTab({ users }: { users: PbxUser[] }) {
    const [items, setItems] = useState<PbxRecording[] | null>(null);
    const [total, setTotal] = useState(0);
    const [policy, setPolicy] = useState<RecordingPolicy | null>(null);
    const [syncedAt, setSyncedAt] = useState<string | null>(null);
    const [search, setSearch] = useState("");
    const [saving, setSaving] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [audio, setAudio] = useState<Record<number, string>>({});
    const [open, setOpen] = useState<number | null>(null);

    const load = useCallback(async (query = "") => {
        const response = await listRecordingsApiV1PbxRecordingsGet({ query: { search: query || undefined, limit: 50 } });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Chargement impossible"));
            setItems([]);
            return;
        }
        const data = response.data as unknown as { items: PbxRecording[]; total: number; policy: RecordingPolicy; synced_at: string | null };
        setItems(data.items);
        setTotal(data.total);
        setPolicy((current) => current ?? data.policy);
        setSyncedAt(data.synced_at);
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    useEffect(() => {
        if (items === null) return;
        const timer = setTimeout(() => void load(search.trim()), 300);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search]);

    const set = (patch: Partial<RecordingPolicy>) => setPolicy((p) => (p ? { ...p, ...patch } : p));
    const recordsAnything = policy && (policy.incoming_external || policy.outgoing_external || policy.internal);

    return (
        <div className="space-y-4">
            <PageSection
                title={
                    <span className="flex items-center gap-2">
                        <Disc3 className="size-5 text-red-300" /> Enregistrement des appels humains
                    </span>
                }
                description="Ce que le PBX enregistre, et ce que la plateforme en fait : copie sécurisée, transcription masquée, conservation selon votre politique de confidentialité."
            >
                {policy && (
                    <div className="grid gap-6 lg:grid-cols-2" data-testid="recording-policy">
                        <div className="space-y-3">
                            <Label>Appels enregistrés</Label>
                            {(
                                [
                                    ["incoming_external", "Appels reçus de l'extérieur"],
                                    ["outgoing_external", "Appels passés vers l'extérieur"],
                                    ["internal", "Appels entre postes"],
                                ] as const
                            ).map(([key, label]) => (
                                <label key={key} className="flex items-center justify-between gap-3 text-sm">
                                    {label}
                                    <Switch aria-label={label} checked={policy[key]} onCheckedChange={(v) => set({ [key]: v })} />
                                </label>
                            ))}
                            <RadioGroup
                                value={policy.user_uuids === null ? "all" : "some"}
                                onValueChange={(v) => set({ user_uuids: v === "all" ? null : [] })}
                                className="flex gap-4 pt-1"
                            >
                                <label className="flex items-center gap-2 text-sm">
                                    <RadioGroupItem value="all" aria-label="Tous les postes" /> Tous les postes
                                </label>
                                <label className="flex items-center gap-2 text-sm">
                                    <RadioGroupItem value="some" aria-label="Certains postes" /> Certains postes
                                </label>
                            </RadioGroup>
                            {policy.user_uuids !== null && (
                                <div className="grid max-h-40 gap-1 overflow-auto rounded-md border border-border/60 p-2 sm:grid-cols-2">
                                    {users.map((u) => (
                                        <label key={u.uuid} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40">
                                            <Checkbox
                                                aria-label={u.name}
                                                checked={policy.user_uuids?.includes(u.uuid) ?? false}
                                                onCheckedChange={(v) =>
                                                    set({ user_uuids: v ? [...(policy.user_uuids ?? []), u.uuid] : (policy.user_uuids ?? []).filter((x) => x !== u.uuid) })
                                                }
                                            />
                                            {u.name}
                                        </label>
                                    ))}
                                </div>
                            )}
                            {recordsAnything && (
                                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
                                    Informez vos correspondants que les appels peuvent être enregistrés (message d&apos;accueil d&apos;un serveur vocal, par exemple).
                                </p>
                            )}
                        </div>
                        <div className="space-y-3">
                            <Label>Dans la plateforme</Label>
                            <label className="flex items-center justify-between gap-3 text-sm">
                                <span>
                                    Copier les enregistrements dans la plateforme
                                    <span className="block text-xs text-muted-foreground">Dès la fin de l&apos;appel, puis vérification toutes les 10 minutes.</span>
                                </span>
                                <Switch aria-label="Copier les enregistrements" checked={policy.import_enabled} onCheckedChange={(v) => set({ import_enabled: v })} />
                            </label>
                            <label className="flex items-center justify-between gap-3 text-sm">
                                <span>
                                    Transcrire les appels
                                    <span className="block text-xs text-muted-foreground">
                                        Avec votre reconnaissance vocale ; cartes, cryptogrammes, IBAN et n° de sécurité sociale toujours masqués.
                                    </span>
                                </span>
                                <Switch aria-label="Transcrire les appels" disabled={!policy.import_enabled} checked={policy.transcribe} onCheckedChange={(v) => set({ transcribe: v })} />
                            </label>
                            <label className="flex items-center justify-between gap-3 text-sm">
                                <span>
                                    Retirer du PBX une fois copiés
                                    <span className="block text-xs text-muted-foreground">Une seule copie, dans le stockage de la plateforme.</span>
                                </span>
                                <Switch aria-label="Retirer du PBX" disabled={!policy.import_enabled} checked={policy.remove_from_pbx} onCheckedChange={(v) => set({ remove_from_pbx: v })} />
                            </label>
                            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                <ShieldCheck className="size-3.5" /> Durée de conservation et droit à l&apos;effacement : page Confidentialité.
                            </p>
                            <div className="flex justify-end">
                                <Button
                                    disabled={saving || (policy.user_uuids !== null && policy.user_uuids.length === 0 && Boolean(recordsAnything))}
                                    onClick={async () => {
                                        setSaving(true);
                                        const response = await saveRecordingPolicyApiV1PbxRecordingsPolicyPut({ body: policy });
                                        setSaving(false);
                                        if (response.error || !response.data) {
                                            toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                            return;
                                        }
                                        const changed = (response.data as { extensions_changed: number }).extensions_changed;
                                        toast.success(changed ? `Réglage appliqué à ${changed} poste(s)` : "Réglage enregistré");
                                    }}
                                >
                                    {saving ? <Loader2 className="animate-spin" /> : <Save />} Appliquer
                                </Button>
                            </div>
                        </div>
                    </div>
                )}
            </PageSection>

            <PageSection
                title={`Enregistrements (${total})`}
                description={syncedAt ? `Dernière vérification : ${fmt(syncedAt)}` : undefined}
                actions={
                    <Button
                        variant="outline"
                        disabled={syncing}
                        onClick={async () => {
                            setSyncing(true);
                            const response = await syncRecordingsApiV1PbxRecordingsSyncPost();
                            setSyncing(false);
                            if (response.error) {
                                toast.error(detailFromError(response.error, "Import impossible"));
                                return;
                            }
                            toast.success(`${(response.data as { imported: number }).imported} enregistrement(s) importé(s)`);
                            void load(search.trim());
                        }}
                    >
                        {syncing ? <Loader2 className="animate-spin" /> : <RefreshCw />} Importer maintenant
                    </Button>
                }
                toolbar={
                    <div className="relative w-full max-w-sm">
                        <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                        <Input aria-label="Rechercher" className="pl-8" placeholder="Numéro, nom ou mot prononcé" value={search} onChange={(e) => setSearch(e.target.value)} />
                    </div>
                }
            >
                {items === null ? null : items.length === 0 ? (
                    <p className="py-8 text-center text-sm text-muted-foreground">Aucun enregistrement.</p>
                ) : (
                    <div className="space-y-2">
                        {items.map((r) => (
                            <div key={r.id} className="rounded-lg border border-border/60 p-3" data-testid="pbx-recording">
                                <div className="flex min-w-0 flex-wrap items-center gap-3">
                                    <div className="min-w-0 flex-1">
                                        <p className="text-sm font-medium">
                                            {party(r.source_name, r.source)} → {party(r.destination_name, r.destination)}
                                        </p>
                                        <p className="text-xs text-muted-foreground">
                                            {fmt(r.started_at)} · {DIRECTION_LABELS[r.direction ?? ""] ?? "—"} · {duration(r.duration_seconds)}
                                            {r.removed_from_pbx && (
                                                <span className="ml-2 inline-flex items-center gap-1">
                                                    <CircleCheck className="size-3" /> copie unique
                                                </span>
                                            )}
                                        </p>
                                    </div>
                                    {r.transcript && (
                                        <Button variant="ghost" size="sm" onClick={() => setOpen(open === r.id ? null : r.id)}>
                                            <FileText /> Transcription {open === r.id ? <ChevronUp /> : <ChevronDown />}
                                        </Button>
                                    )}
                                    {TRANSCRIPT[r.transcript_status] && <Badge variant="outline">{TRANSCRIPT[r.transcript_status]}</Badge>}
                                    {audio[r.id] ? (
                                        <audio controls autoPlay src={audio[r.id]} className="h-8 w-64 max-w-full" data-testid="recording-audio" />
                                    ) : (
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            aria-label={`Écouter l'appel ${r.id}`}
                                            onClick={async () => {
                                                const response = await recordingAudioApiV1PbxRecordingsRecordingIdAudioGet({ path: { recording_id: r.id } });
                                                if (response.error || !response.data) {
                                                    toast.error(detailFromError(response.error, "Écoute impossible"));
                                                    return;
                                                }
                                                setAudio((a) => ({ ...a, [r.id]: (response.data as { url: string }).url }));
                                            }}
                                        >
                                            <Play /> Écouter
                                        </Button>
                                    )}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="text-destructive"
                                        aria-label={`Supprimer l'enregistrement ${r.id}`}
                                        onClick={async () => {
                                            if (!window.confirm("Supprimer définitivement cet enregistrement ?")) return;
                                            const response = await deleteRecordingApiV1PbxRecordingsRecordingIdDelete({ path: { recording_id: r.id } });
                                            if (response.error) {
                                                toast.error(detailFromError(response.error, "Suppression impossible"));
                                                return;
                                            }
                                            toast.success("Enregistrement supprimé");
                                            void load(search.trim());
                                        }}
                                    >
                                        <Trash2 />
                                    </Button>
                                </div>
                                {open === r.id && r.transcript && (
                                    <p className="mt-2 whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-sm" data-testid="recording-transcript">
                                        {r.transcript}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </PageSection>
        </div>
    );
}

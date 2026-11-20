"use client";

import { Download, Eraser, Eye, FileClock, ShieldCheck, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    eraseApiV1PrivacyErasurePost,
    exportApiV1PrivacyExportPost,
    listRequestsApiV1PrivacyRequestsGet,
    previewRedactionApiV1PrivacyPreviewPost,
    readSettingsApiV1PrivacySettingsGet,
    updateSettingsApiV1PrivacySettingsPut,
} from "@/client/sdk.gen";
import type { PrivacyRequestResponse, PrivacySettings } from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

const CATEGORY_LABELS: Record<string, { label: string; example: string }> = {
    card: { label: "Cartes bancaires", example: "4111 1111 1111 1111 (contrôle Luhn)" },
    cvv: { label: "Cryptogrammes", example: "« cryptogramme 123 »" },
    iban: { label: "IBAN", example: "FR76 3000 6000 0112 …" },
    ssn: { label: "N° de sécurité sociale", example: "NIR français, SSN américain" },
    email: { label: "E-mails", example: "écrits ou dictés (« arobase »)" },
    phone: { label: "Téléphones", example: "+227 90 12 34 56, 06 12 34 56 78" },
    ip: { label: "Adresses IP", example: "192.168.1.20" },
};

const DEFAULT_SETTINGS: PrivacySettings = {
    redaction_enabled: false,
    categories: Object.keys(CATEGORY_LABELS),
    mask_in_conversation: false,
    redact_extracted_data: false,
    store_recordings: true,
    recording_retention_days: null,
    transcript_retention_days: null,
    customer_memory_retention_days: null,
};

const RETENTION_FIELDS: { key: keyof PrivacySettings; label: string; hint: string }[] = [
    { key: "recording_retention_days", label: "Enregistrements audio", hint: "fichiers audio des appels" },
    { key: "transcript_retention_days", label: "Transcriptions", hint: "texte des conversations" },
    { key: "customer_memory_retention_days", label: "Mémoire client", hint: "historique et fiches inactives" },
];

function ToggleRow({
    id,
    title,
    hint,
    checked,
    onChange,
}: {
    id: string;
    title: string;
    hint: string;
    checked: boolean;
    onChange: (value: boolean) => void;
}) {
    return (
        <div className="flex items-start justify-between gap-6">
            <div>
                <Label htmlFor={id}>{title}</Label>
                <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
            </div>
            <Switch id={id} checked={checked} onCheckedChange={onChange} />
        </div>
    );
}

function downloadJson(data: unknown, filename: string) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
}

export default function PrivacyPage() {
    const { user, loading: authLoading } = useAuth();
    const fetched = useRef(false);
    const [saved, setSaved] = useState<PrivacySettings | null>(null);
    const [settings, setSettings] = useState<PrivacySettings>(DEFAULT_SETTINGS);
    const [saving, setSaving] = useState(false);
    const [requests, setRequests] = useState<PrivacyRequestResponse[]>([]);
    const [sample, setSample] = useState(
        "Bonjour, ma carte c'est 4111 1111 1111 1111, cryptogramme 123, et mon mail jean.dupont@gmail.com.",
    );
    const [preview, setPreview] = useState<string | null>(null);
    const [phone, setPhone] = useState("");
    const [busy, setBusy] = useState<"export" | "erase" | null>(null);
    const [confirmErase, setConfirmErase] = useState(false);

    const loadRequests = useCallback(async () => {
        const response = await listRequestsApiV1PrivacyRequestsGet();
        if (!response.error && response.data) setRequests(response.data);
    }, []);

    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void (async () => {
            const response = await readSettingsApiV1PrivacySettingsGet();
            if (response.error || !response.data) {
                toast.error(detailFromError(response.error, "Chargement impossible"));
                setSaved(DEFAULT_SETTINGS);
                return;
            }
            const { available_categories: _available, ...current } = response.data;
            void _available;
            setSaved(current);
            setSettings(current);
        })();
        void loadRequests();
    }, [authLoading, user, loadRequests]);

    const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(settings);
    const set = <K extends keyof PrivacySettings>(key: K, value: PrivacySettings[K]) =>
        setSettings((s) => ({ ...s, [key]: value }));
    const categories = settings.categories ?? [];

    const save = async () => {
        setSaving(true);
        const response = await updateSettingsApiV1PrivacySettingsPut({ body: settings });
        setSaving(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        const { available_categories: _available, ...current } = response.data;
        void _available;
        setSaved(current);
        setSettings(current);
        toast.success("Politique de confidentialité enregistrée. Elle s'applique aux prochains appels.");
    };

    const runPreview = async () => {
        const response = await previewRedactionApiV1PrivacyPreviewPost({
            body: { text: sample, categories },
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Aperçu impossible"));
            return;
        }
        setPreview(response.data.text);
    };

    const exportData = async () => {
        setBusy("export");
        const response = await exportApiV1PrivacyExportPost({ body: { phone } });
        setBusy(null);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Export impossible"));
            return;
        }
        downloadJson(response.data, `export-rgpd-${phone.replace(/\D/g, "").slice(-4)}.json`);
        toast.success("Export téléchargé.");
        void loadRequests();
    };

    const erase = async () => {
        setConfirmErase(false);
        setBusy("erase");
        const response = await eraseApiV1PrivacyErasurePost({ body: { phone } });
        setBusy(null);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Effacement impossible"));
            return;
        }
        const counts = response.data.counts as Record<string, number>;
        toast.success(
            `Données effacées : ${counts.calls ?? 0} appel(s), ${counts.files ?? 0} fichier(s), ${counts.customer_profiles ?? 0} fiche(s) client.`,
        );
        setPhone("");
        void loadRequests();
    };

    if (saved === null) {
        return (
            <PageLayout title="Confidentialité">
                <Skeleton className="h-64 w-full" />
            </PageLayout>
        );
    }

    return (
        <PageLayout
            title="Confidentialité"
            description="RGPD et PCI DSS : ce que NIMBORA masque, conserve et efface pour votre organisation."
            actions={
                <Button onClick={save} disabled={!dirty || saving}>
                    <ShieldCheck className="mr-2 h-4 w-4" />
                    {saving ? "Enregistrement…" : "Enregistrer la politique"}
                </Button>
            }
        >
            <PageSection
                title="Masquage des données personnelles"
                description="Appliqué à tout ce qui est conservé : transcriptions, journaux d'appels, fiches de passation, mémoire client et analyses QA."
            >
                <div className="space-y-6">
                    <ToggleRow
                        id="redaction-enabled"
                        title="Masquer les données personnelles conservées"
                        hint="Les valeurs sont remplacées par [CARD], [EMAIL], [PHONE]… avant tout enregistrement."
                        checked={settings.redaction_enabled ?? false}
                        onChange={(v) => set("redaction_enabled", v)}
                    />
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        {Object.entries(CATEGORY_LABELS).map(([code, { label, example }]) => {
                            const on = categories.includes(code);
                            return (
                                <button
                                    key={code}
                                    type="button"
                                    aria-pressed={on}
                                    disabled={!settings.redaction_enabled}
                                    onClick={() =>
                                        set(
                                            "categories",
                                            on ? categories.filter((c) => c !== code) : [...categories, code],
                                        )
                                    }
                                    className={`rounded-lg border p-3 text-left transition disabled:opacity-50 ${
                                        on && settings.redaction_enabled
                                            ? "border-primary bg-primary/10"
                                            : "border-border/60 hover:bg-accent/40"
                                    }`}
                                >
                                    <span className="block text-sm font-medium">{label}</span>
                                    <span className="mt-0.5 block text-xs text-muted-foreground">{example}</span>
                                </button>
                            );
                        })}
                    </div>
                    <ToggleRow
                        id="redact-extracted"
                        title="Masquer aussi les données extraites"
                        hint="Variables collectées par les agents (e-mail, téléphone…). Laissez désactivé si vos webhooks en ont besoin."
                        checked={settings.redact_extracted_data ?? false}
                        onChange={(v) => set("redact_extracted_data", v)}
                    />
                    <ToggleRow
                        id="mask-in-conversation"
                        title="Mode PCI : l'agent IA n'entend jamais les numéros de carte"
                        hint="Cartes, cryptogrammes, IBAN et n° de sécurité sociale sont masqués dès la reconnaissance vocale : ni le modèle, ni la supervision en direct, ni les journaux ne les voient."
                        checked={settings.mask_in_conversation ?? false}
                        onChange={(v) => set("mask_in_conversation", v)}
                    />

                    <div className="rounded-xl border border-border/60 bg-card/40 p-4">
                        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                            <Sparkles className="h-4 w-4 text-cyan-400" />
                            Essayer le masquage
                        </div>
                        <Textarea rows={2} value={sample} onChange={(e) => setSample(e.target.value)} />
                        <div className="mt-2 flex flex-wrap items-center gap-3">
                            <Button size="sm" variant="outline" onClick={runPreview}>
                                <Eye className="mr-1 h-4 w-4" />
                                Aperçu
                            </Button>
                            {preview !== null && (
                                <p data-testid="redaction-preview" className="font-mono text-sm text-emerald-300">
                                    {preview}
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            </PageSection>

            <PageSection
                title="Conservation"
                description="Au-delà de ces durées, une purge quotidienne efface les contenus. Les métadonnées d'appel (date, durée, coût) restent pour la facturation."
            >
                <div className="space-y-6">
                    <ToggleRow
                        id="store-recordings"
                        title="Enregistrer l'audio des appels"
                        hint="Désactivé : aucun fichier audio n'est conservé."
                        checked={settings.store_recordings ?? true}
                        onChange={(v) => set("store_recordings", v)}
                    />
                    <div className="grid gap-4 sm:grid-cols-3">
                        {RETENTION_FIELDS.map(({ key, label, hint }) => (
                            <div key={key} className="space-y-1.5">
                                <Label htmlFor={`retention-${key}`}>{label}</Label>
                                <div className="flex items-center gap-2">
                                    <Input
                                        id={`retention-${key}`}
                                        type="number"
                                        min={1}
                                        max={3650}
                                        placeholder="Illimitée"
                                        value={(settings[key] as number | null | undefined) ?? ""}
                                        onChange={(e) =>
                                            set(key, (e.target.value ? Number(e.target.value) : null) as never)
                                        }
                                    />
                                    <span className="text-sm text-muted-foreground">jours</span>
                                </div>
                                <p className="text-xs text-muted-foreground">{hint}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </PageSection>

            <PageSection
                title="Droits des personnes"
                description="Droit d'accès (art. 15) et droit à l'effacement (art. 17), à partir du numéro de téléphone de la personne."
            >
                <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="subject-phone">Numéro de téléphone</Label>
                        <Input
                            id="subject-phone"
                            className="w-64"
                            placeholder="+227 90 12 34 56"
                            value={phone}
                            onChange={(e) => setPhone(e.target.value)}
                        />
                    </div>
                    <Button variant="outline" disabled={phone.trim().length < 6 || busy !== null} onClick={exportData}>
                        <Download className="mr-2 h-4 w-4" />
                        {busy === "export" ? "Export…" : "Exporter ses données"}
                    </Button>
                    <Button
                        variant="destructive"
                        disabled={phone.trim().length < 6 || busy !== null}
                        onClick={() => setConfirmErase(true)}
                    >
                        <Eraser className="mr-2 h-4 w-4" />
                        {busy === "erase" ? "Effacement…" : "Effacer ses données"}
                    </Button>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                    L&apos;effacement supprime enregistrements et transcriptions, anonymise les appels (conservés pour la
                    facturation), et supprime la fiche client, les passations et les rappels. Le registre ne conserve
                    jamais le numéro en clair.
                </p>

                <div className="mt-6">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                        <FileClock className="h-4 w-4" />
                        Registre des demandes
                    </div>
                    {requests.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Aucune demande pour l&apos;instant.</p>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Date</TableHead>
                                    <TableHead>Demande</TableHead>
                                    <TableHead>Personne</TableHead>
                                    <TableHead>Résultat</TableHead>
                                    <TableHead>Statut</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {requests.map((r) => {
                                    const counts = r.counts as Record<string, number>;
                                    return (
                                        <TableRow key={r.id}>
                                            <TableCell className="text-sm">
                                                {r.created_at ? new Date(r.created_at).toLocaleString("fr-FR") : ""}
                                            </TableCell>
                                            <TableCell>
                                                {r.kind === "erasure" ? "Effacement" : "Export"}
                                            </TableCell>
                                            <TableCell className="font-mono text-sm">{r.subject_hint}</TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                {counts.calls ?? 0} appel(s) · {counts.customer_profiles ?? 0} fiche(s)
                                                {r.kind === "erasure" ? ` · ${counts.files ?? 0} fichier(s)` : ""}
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={r.status === "done" ? "default" : r.status === "failed" ? "destructive" : "secondary"}>
                                                    {r.status === "done" ? "Terminé" : r.status === "failed" ? "Échec" : "En cours"}
                                                </Badge>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    )}
                </div>
            </PageSection>

            <AlertDialog open={confirmErase} onOpenChange={setConfirmErase}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Effacer toutes les données de {phone} ?</AlertDialogTitle>
                        <AlertDialogDescription>
                            Enregistrements, transcriptions, fiche client, passations et rappels liés à ce numéro seront
                            supprimés définitivement. Cette action est irréversible.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Annuler</AlertDialogCancel>
                        <AlertDialogAction onClick={erase}>Effacer définitivement</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </PageLayout>
    );
}

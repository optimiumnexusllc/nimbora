"use client";

import { ClipboardCheck, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    listQualityReviewsApiV1QualityReviewsGet,
    qualitySummaryApiV1QualitySummaryGet,
    readQualitySettingsApiV1QualitySettingsGet,
    saveQualitySettingsApiV1QualitySettingsPut,
} from "@/client/sdk.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { ReviewSheet } from "@/components/quality/ReviewSheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import {
    agentLabel,
    type Criterion,
    durationText,
    percentText,
    type QualitySettings,
    type ReviewRow,
    type ReviewStatus,
    scoreText,
    STATUS_LABELS,
    type Summary,
} from "@/lib/quality";

const PERIODS = [7, 30, 90] as const;

function Stat({ label, value }: { label: string; value: string }) {
    return (
        <Card data-testid="quality-stat">
            <CardContent className="space-y-1 p-4">
                <p className="text-sm text-muted-foreground">{label}</p>
                <p className="text-2xl font-semibold tabular-nums">{value}</p>
            </CardContent>
        </Card>
    );
}

function GridEditor({ onSaved }: { onSaved: () => void }) {
    const { user, loading } = useAuth();
    const [settings, setSettings] = useState<QualitySettings | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (loading || !user) return;
        void (async () => {
            const response = await readQualitySettingsApiV1QualitySettingsGet();
            if (response.data) setSettings(response.data as QualitySettings);
        })();
    }, [loading, user]);

    if (!settings) return <p className="text-sm text-muted-foreground">Chargement…</p>;
    const update = (i: number, patch: Partial<Criterion>) =>
        setSettings({ ...settings, criteria: settings.criteria.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

    return (
        <div className="space-y-6">
            <PageSection title="Grille d'évaluation" description="Ce qu'un bon appel doit contenir. Le poids (1 à 5) compte dans la note sur 100 ; « Sans objet » ne pénalise jamais.">
                <ul className="space-y-3" data-testid="grid">
                    {settings.criteria.map((c, i) => (
                        <li key={i} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[1fr_2fr_auto_auto]">
                            <Input aria-label="Critère" value={c.label} maxLength={80} onChange={(e) => update(i, { label: e.target.value })} />
                            <Input aria-label="Ce qui est attendu" placeholder="Ce qui est attendu" value={c.description} maxLength={300} onChange={(e) => update(i, { description: e.target.value })} />
                            <Select value={String(c.weight)} onValueChange={(v) => update(i, { weight: Number(v) })}>
                                <SelectTrigger className="w-28" aria-label="Poids">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {[1, 2, 3, 4, 5].map((w) => (
                                        <SelectItem key={w} value={String(w)}>
                                            Poids {w}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Retirer ${c.label}`}
                                disabled={settings.criteria.length === 1}
                                onClick={() => setSettings({ ...settings, criteria: settings.criteria.filter((_, j) => j !== i) })}
                            >
                                <Trash2 />
                            </Button>
                        </li>
                    ))}
                </ul>
                <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    disabled={settings.criteria.length >= 15}
                    onClick={() => setSettings({ ...settings, criteria: [...settings.criteria, { key: "", label: "Nouveau critère", description: "", weight: 1 }] })}
                >
                    <Plus /> Ajouter un critère
                </Button>
            </PageSection>
            <PageSection title="Évaluation automatique" description="Les appels enregistrés et transcrits sont évalués par l'IA dès leur arrivée ; un superviseur valide ensuite.">
                <div className="flex flex-wrap items-center gap-6">
                    <Label className="flex items-center gap-2">
                        <Switch checked={settings.auto_evaluate} onCheckedChange={(v) => setSettings({ ...settings, auto_evaluate: v })} /> Évaluer automatiquement
                    </Label>
                    <Label className="flex items-center gap-2">
                        Part des appels
                        <Input
                            type="number"
                            className="w-20"
                            min={1}
                            max={100}
                            value={settings.sample_percent}
                            disabled={!settings.auto_evaluate}
                            onChange={(e) => setSettings({ ...settings, sample_percent: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })}
                        />
                        %
                    </Label>
                </div>
            </PageSection>
            <div className="flex justify-end">
                <Button
                    disabled={saving}
                    onClick={async () => {
                        setSaving(true);
                        const response = await saveQualitySettingsApiV1QualitySettingsPut({ body: settings });
                        setSaving(false);
                        if (response.error) {
                            toast.error(detailFromError(response.error, "Grille non enregistrée"));
                            return;
                        }
                        setSettings(response.data as QualitySettings);
                        toast.success("Grille enregistrée : elle s'applique aux prochaines évaluations");
                        onSaved();
                    }}
                >
                    {saving ? <Loader2 className="animate-spin" /> : <Save />} Enregistrer la grille
                </Button>
            </div>
        </div>
    );
}

export default function QualityPage() {
    const { user, loading } = useAuth();
    const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
    const [status, setStatus] = useState<ReviewStatus | "all">("all");
    const [rows, setRows] = useState<ReviewRow[] | null>(null);
    const [summary, setSummary] = useState<Summary | null>(null);
    const [open, setOpen] = useState<number | null>(null);

    const load = useCallback(async () => {
        const [list, stats] = await Promise.all([
            listQualityReviewsApiV1QualityReviewsGet({ query: { days, status: status === "all" ? undefined : status, limit: 100 } }),
            qualitySummaryApiV1QualitySummaryGet({ query: { days } }),
        ]);
        if (list.error || stats.error) {
            toast.error(detailFromError(list.error ?? stats.error, "Contrôle qualité indisponible"));
            return;
        }
        setRows((list.data as { items: ReviewRow[] }).items);
        setSummary(stats.data as unknown as Summary);
    }, [days, status]);

    useEffect(() => {
        if (loading || !user) return;
        void load();
    }, [loading, user, load]);

    // Opened from PBX → Enregistrements: /quality?review=<id>
    useEffect(() => {
        const id = Number(new URLSearchParams(window.location.search).get("review"));
        if (id) setOpen(id);
    }, []);
    const close = useCallback(() => setOpen(null), []);

    return (
        <PageLayout
            title="Contrôle qualité"
            description="Les appels de vos conseillers, évalués selon votre grille : par l'IA à partir de la transcription, puis validés par un superviseur."
            width="full"
            actions={
                <div className="flex rounded-lg border border-border/60 p-0.5" role="group" aria-label="Période">
                    {PERIODS.map((d) => (
                        <Button key={d} size="sm" variant={days === d ? "secondary" : "ghost"} aria-pressed={days === d} onClick={() => setDays(d)}>
                            {d} jours
                        </Button>
                    ))}
                </div>
            }
        >
            <Tabs defaultValue="calls">
                <TabsList>
                    <TabsTrigger value="calls">Appels évalués</TabsTrigger>
                    <TabsTrigger value="agents">Conseillers</TabsTrigger>
                    <TabsTrigger value="grid">Grille</TabsTrigger>
                </TabsList>

                <TabsContent value="calls" className="space-y-6">
                    {summary && (
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                            <Stat label="Note moyenne" value={scoreText(summary.average)} />
                            <Stat label="Appels évalués" value={String(summary.evaluated)} />
                            <Stat label="À valider par un superviseur" value={String(summary.to_review)} />
                            <Stat label="Échecs de l'IA" value={String(summary.failed)} />
                        </div>
                    )}
                    <PageSection
                        title="Appels"
                        description="Pour évaluer un appel, ouvrez PBX → Enregistrements puis « Évaluer »."
                        actions={
                            <Select value={status} onValueChange={(v) => setStatus(v as ReviewStatus | "all")}>
                                <SelectTrigger className="w-44" aria-label="Statut">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Tous les statuts</SelectItem>
                                    {(Object.keys(STATUS_LABELS) as ReviewStatus[]).map((s) => (
                                        <SelectItem key={s} value={s}>
                                            {STATUS_LABELS[s]}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        }
                    >
                        {rows === null ? (
                            <p className="text-sm text-muted-foreground">Chargement…</p>
                        ) : rows.length === 0 ? (
                            <div className="py-10 text-center text-sm text-muted-foreground">
                                <ClipboardCheck className="mx-auto mb-2 size-6" aria-hidden />
                                Aucun appel évalué sur la période.
                            </div>
                        ) : (
                            <Table data-testid="reviews">
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Date</TableHead>
                                        <TableHead>Conseiller</TableHead>
                                        <TableHead>Durée</TableHead>
                                        <TableHead>Statut</TableHead>
                                        <TableHead className="text-right">Note IA</TableHead>
                                        <TableHead className="text-right">Note retenue</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {rows.map((r) => (
                                        <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                                            <TableCell>{r.started_at ? new Date(r.started_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</TableCell>
                                            <TableCell>
                                                <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => setOpen(r.id)}>
                                                    {agentLabel(r)}
                                                </button>
                                            </TableCell>
                                            <TableCell className="tabular-nums">{durationText(r.duration_seconds)}</TableCell>
                                            <TableCell>
                                                <Badge variant={r.status === "reviewed" ? "secondary" : "outline"}>{STATUS_LABELS[r.status]}</Badge>
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">{scoreText(r.ai_score)}</TableCell>
                                            <TableCell className="text-right font-medium tabular-nums">{scoreText(r.score)}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </PageSection>
                </TabsContent>

                <TabsContent value="agents" className="space-y-6">
                    <PageSection title="Par conseiller" description="Note moyenne des appels évalués sur la période (celle du superviseur quand elle existe).">
                        {!summary?.agents.length ? (
                            <p className="text-sm text-muted-foreground">Aucun appel évalué sur la période.</p>
                        ) : (
                            <Table data-testid="agents">
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Conseiller</TableHead>
                                        <TableHead className="text-right">Appels évalués</TableHead>
                                        <TableHead className="text-right">Validés</TableHead>
                                        <TableHead className="text-right">Note moyenne</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {summary.agents.map((a) => (
                                        <TableRow key={a.agent_extension ?? "?"}>
                                            <TableCell>{agentLabel(a)}</TableCell>
                                            <TableCell className="text-right tabular-nums">{a.evaluated}</TableCell>
                                            <TableCell className="text-right tabular-nums">{a.reviewed}</TableCell>
                                            <TableCell className="text-right font-medium tabular-nums">{scoreText(a.average)}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </PageSection>
                    <PageSection title="Par critère" description="Part des appels où le critère est respecté (« En partie » compte pour moitié, « Sans objet » est exclu).">
                        <Table data-testid="criteria-rates">
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Critère</TableHead>
                                    <TableHead className="text-right">Appels concernés</TableHead>
                                    <TableHead className="text-right">Respecté</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {summary?.criteria.map((c) => (
                                    <TableRow key={c.key}>
                                        <TableCell>{c.label}</TableCell>
                                        <TableCell className="text-right tabular-nums">{c.answered}</TableCell>
                                        <TableCell className="text-right font-medium tabular-nums">{percentText(c.rate)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </PageSection>
                </TabsContent>

                <TabsContent value="grid">
                    <GridEditor onSaved={() => void load()} />
                </TabsContent>
            </Tabs>
            <ReviewSheet reviewId={open} onClose={close} onSaved={() => void load()} />
        </PageLayout>
    );
}

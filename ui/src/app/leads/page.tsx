"use client";

import { Download, Phone, Plus, Search, Target, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createLeadApiV1LeadsPost,
    deleteLeadApiV1LeadsLeadIdDelete,
    exportLeadsApiV1LeadsExportCsvGet,
    listLeadsApiV1LeadsGet,
    moveLeadApiV1LeadsLeadIdStagePost,
    updateLeadApiV1LeadsLeadIdPut,
} from "@/client/sdk.gen";
import { PageLayout } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { download } from "@/lib/catalog";
import { EMPTY_LEAD, type Lead, type LeadForm, leadFromForm, leadToForm, type PipelineStage, SOURCES, type Stage, STAGES, temperature } from "@/lib/leads";
import { cn } from "@/lib/utils";

export default function LeadsPage() {
    const { user, loading: authLoading } = useAuth();
    const fetched = useRef(false);
    const [leads, setLeads] = useState<Lead[] | null>(null);
    const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
    const [query, setQuery] = useState("");
    const [open, setOpen] = useState<{ id: number | null; form: LeadForm; interests: string[] } | null>(null);

    const load = useCallback(async () => {
        const response = await listLeadsApiV1LeadsGet({ query: { q: query || null } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Prospects indisponibles"));
            return;
        }
        const data = response.data as unknown as { leads: Lead[]; pipeline: PipelineStage[] };
        setLeads(data.leads);
        setPipeline(data.pipeline);
    }, [query]);

    useEffect(() => {
        if (authLoading || !user) return;
        const timer = setTimeout(() => void load(), fetched.current ? 250 : 0);
        fetched.current = true;
        return () => clearTimeout(timer);
    }, [authLoading, user, load]);

    const move = async (lead: Lead, stage: Stage) => {
        let lost_reason: string | null = null;
        if (stage === "lost") lost_reason = window.prompt(`Pourquoi « ${lead.name || lead.phone || "ce prospect"} » est-il perdu ?`) ?? null;
        const response = await moveLeadApiV1LeadsLeadIdStagePost({ path: { lead_id: lead.id }, body: { stage, lost_reason } });
        if (response.error) toast.error(detailFromError(response.error, "Changement impossible"));
        else void load();
    };

    const save = async () => {
        if (!open) return;
        const body = leadFromForm(open.form, open.interests);
        const response = open.id === null ? await createLeadApiV1LeadsPost({ body }) : await updateLeadApiV1LeadsLeadIdPut({ path: { lead_id: open.id }, body });
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        toast.success("Prospect enregistré");
        setOpen(null);
        void load();
    };

    const set = (patch: Partial<LeadForm>) => open && setOpen({ ...open, form: { ...open.form, ...patch } });
    const byStage = (stage: Stage) => (leads ?? []).filter((l) => l.stage === stage);

    return (
        <PageLayout
            title="Prospects"
            description="Les agents qualifient les appelants (besoin, budget, échéance, décideur) avec l'outil « Qualify Lead » ; faites avancer chaque prospect jusqu'à la vente."
            width="full"
            actions={
                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="outline"
                        onClick={async () => {
                            const response = await exportLeadsApiV1LeadsExportCsvGet({ parseAs: "text" });
                            if (response.error) toast.error(detailFromError(response.error, "Export impossible"));
                            else download("prospects.csv", response.data as unknown as string);
                        }}
                    >
                        <Download /> Exporter
                    </Button>
                    <Button onClick={() => setOpen({ id: null, form: EMPTY_LEAD, interests: [] })}>
                        <Plus /> Nouveau prospect
                    </Button>
                </div>
            }
        >
            <label className="relative mb-4 block max-w-md">
                <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
                <Input aria-label="Rechercher un prospect" className="pl-9" placeholder="Nom, numéro, société, besoin…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            {leads === null ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Chargement…</p>
            ) : (
                <div className="grid gap-3 overflow-x-auto pb-2 md:grid-cols-3 xl:grid-cols-6" data-testid="pipeline">
                    {STAGES.map(({ value, label }) => {
                        const column = pipeline.find((p) => p.stage === value);
                        return (
                            <section key={value} className="min-w-56 rounded-xl border border-border/60 bg-muted/20 p-2" data-testid={`stage-${value}`}>
                                <header className="mb-2 px-1">
                                    <p className="flex items-center justify-between text-sm font-medium">
                                        {label} <Badge variant="outline">{column?.count ?? 0}</Badge>
                                    </p>
                                    {column?.budgets.map((b) => (
                                        <p key={b.currency} className="text-xs text-muted-foreground">
                                            {b.text}
                                        </p>
                                    ))}
                                </header>
                                <div className="space-y-2">
                                    {byStage(value).map((lead) => {
                                        const temp = temperature(lead.score);
                                        return (
                                            <article key={lead.id} className="rounded-lg border border-border/60 bg-background p-2.5 text-sm" data-testid="lead">
                                                <button type="button" className="w-full text-left" onClick={() => setOpen({ id: lead.id, form: leadToForm(lead), interests: lead.interests })}>
                                                    <p className="flex items-start justify-between gap-2 font-medium">
                                                        <span className="truncate">{lead.name || lead.company || lead.phone || "Sans nom"}</span>
                                                        <span className={cn("shrink-0 rounded-full border px-1.5 text-[10px]", temp.className)} title={`Score ${lead.score}/100`}>
                                                            {temp.label} · {lead.score}
                                                        </span>
                                                    </p>
                                                    {lead.need && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{lead.need}</p>}
                                                    {lead.budget_text && <p className="mt-1 text-xs">{lead.budget_text}</p>}
                                                    <p className="mt-1 text-[11px] text-muted-foreground">
                                                        {SOURCES[lead.source] ?? lead.source}
                                                        {lead.timeline ? ` · ${lead.timeline}` : ""}
                                                        {lead.stage === "lost" && lead.lost_reason ? ` · ${lead.lost_reason}` : ""}
                                                    </p>
                                                </button>
                                                <div className="mt-2 flex items-center gap-1">
                                                    <Select value={lead.stage} onValueChange={(v) => void move(lead, v as Stage)}>
                                                        <SelectTrigger aria-label={`Étape de ${lead.name || lead.id}`} className="h-7 text-xs">
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {STAGES.map((s) => (
                                                                <SelectItem key={s.value} value={s.value}>
                                                                    {s.label}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                    {lead.phone && (
                                                        <Button variant="ghost" size="icon" className="size-7" asChild>
                                                            <a href={`tel:${lead.phone}`} aria-label={`Appeler ${lead.name || lead.phone}`}>
                                                                <Phone className="size-3.5" />
                                                            </a>
                                                        </Button>
                                                    )}
                                                </div>
                                            </article>
                                        );
                                    })}
                                    {byStage(value).length === 0 && <p className="px-1 py-3 text-center text-xs text-muted-foreground">—</p>}
                                </div>
                            </section>
                        );
                    })}
                </div>
            )}
            {leads?.length === 0 && !query && (
                <p className="mt-6 flex items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Target className="size-4" /> Ajoutez l&apos;outil « Qualify Lead » à un agent : chaque appelant intéressé apparaîtra ici.
                </p>
            )}

            <Sheet open={open !== null} onOpenChange={(v) => !v && setOpen(null)}>
                <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
                    <SheetHeader>
                        <SheetTitle>{open?.id === null ? "Nouveau prospect" : open?.form.name || "Prospect"}</SheetTitle>
                        <SheetDescription>Le score monte avec chaque information connue : besoin, budget, échéance, décideur, contact, intérêts.</SheetDescription>
                    </SheetHeader>
                    {open && (
                        <div className="grid gap-3 p-4 sm:grid-cols-2">
                            {(
                                [
                                    ["name", "Nom"],
                                    ["company", "Société"],
                                    ["phone", "Téléphone"],
                                    ["email", "E-mail"],
                                ] as const
                            ).map(([key, label]) => (
                                <div key={key} className="space-y-1">
                                    <Label htmlFor={`lead-${key}`}>{label}</Label>
                                    <Input id={`lead-${key}`} value={open.form[key]} onChange={(e) => set({ [key]: e.target.value })} />
                                </div>
                            ))}
                            <div className="space-y-1 sm:col-span-2">
                                <Label htmlFor="lead-need">Besoin</Label>
                                <Textarea id="lead-need" rows={3} value={open.form.need} onChange={(e) => set({ need: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="lead-budget-min">Budget de</Label>
                                <Input id="lead-budget-min" inputMode="decimal" value={open.form.budget_min} onChange={(e) => set({ budget_min: e.target.value })} />
                            </div>
                            <div className="grid grid-cols-[1fr_5rem] gap-2">
                                <div className="space-y-1">
                                    <Label htmlFor="lead-budget-max">à</Label>
                                    <Input id="lead-budget-max" inputMode="decimal" value={open.form.budget_max} onChange={(e) => set({ budget_max: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="lead-currency">Devise</Label>
                                    <Input id="lead-currency" maxLength={3} value={open.form.currency} onChange={(e) => set({ currency: e.target.value })} />
                                </div>
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="lead-timeline">Échéance</Label>
                                <Input id="lead-timeline" placeholder="dans 3 mois" value={open.form.timeline} onChange={(e) => set({ timeline: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label>Décideur</Label>
                                <Select value={open.form.decision_maker || "unknown"} onValueChange={(v) => set({ decision_maker: v === "unknown" ? "" : (v as "yes" | "no") })}>
                                    <SelectTrigger aria-label="Décideur">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="unknown">Inconnu</SelectItem>
                                        <SelectItem value="yes">Décide seul</SelectItem>
                                        <SelectItem value="no">Décide avec d&apos;autres</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="lead-owner">Responsable</Label>
                                <Input id="lead-owner" value={open.form.owner} onChange={(e) => set({ owner: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="lead-next">Prochaine action</Label>
                                <Input id="lead-next" placeholder="Visite samedi 10 h" value={open.form.next_action} onChange={(e) => set({ next_action: e.target.value })} />
                            </div>
                            {open.interests.length > 0 && (
                                <div className="space-y-1 sm:col-span-2">
                                    <Label>Intérêts</Label>
                                    <div className="flex flex-wrap gap-1">
                                        {open.interests.map((i) => (
                                            <Badge key={i} variant="outline">
                                                {i}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="space-y-1 sm:col-span-2">
                                <Label htmlFor="lead-notes">Notes</Label>
                                <Textarea id="lead-notes" rows={4} value={open.form.notes} onChange={(e) => set({ notes: e.target.value })} />
                            </div>
                            <div className="flex justify-between gap-2 sm:col-span-2">
                                {open.id !== null ? (
                                    <Button
                                        variant="ghost"
                                        className="text-destructive"
                                        onClick={async () => {
                                            if (!window.confirm("Supprimer ce prospect ?")) return;
                                            const response = await deleteLeadApiV1LeadsLeadIdDelete({ path: { lead_id: open.id as number } });
                                            if (response.error) toast.error(detailFromError(response.error, "Suppression impossible"));
                                            else {
                                                setOpen(null);
                                                void load();
                                            }
                                        }}
                                    >
                                        <Trash2 /> Supprimer
                                    </Button>
                                ) : (
                                    <span />
                                )}
                                <Button onClick={() => void save()}>Enregistrer</Button>
                            </div>
                        </div>
                    )}
                </SheetContent>
            </Sheet>
        </PageLayout>
    );
}

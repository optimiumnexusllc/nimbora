"use client";

import {
    BedDouble,
    Bot,
    Building2,
    Bus,
    Check,
    Droplets,
    Factory,
    GraduationCap,
    HardHat,
    Home,
    Hospital,
    Landmark,
    Lightbulb,
    type LucideIcon,
    MonitorCog,
    Pickaxe,
    Pill,
    RadioTower,
    Search,
    ShieldAlert,
    ShieldCheck,
    ShieldHalf,
    ShoppingBag,
    Smartphone,
    Stethoscope,
    TrendingUp,
    Truck,
    Wheat,
    Zap,
} from "lucide-react";
import { useMemo, useState } from "react";

import type { TemplateSummary } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export const TEMPLATE_ICONS: Record<string, LucideIcon> = {
    "building-2": Building2,
    "shopping-bag": ShoppingBag,
    home: Home,
    "bed-double": BedDouble,
    "shield-check": ShieldCheck,
    stethoscope: Stethoscope,
    "graduation-cap": GraduationCap,
    landmark: Landmark,
    smartphone: Smartphone,
    "trending-up": TrendingUp,
    hospital: Hospital,
    pill: Pill,
    "radio-tower": RadioTower,
    "monitor-cog": MonitorCog,
    zap: Zap,
    droplets: Droplets,
    bus: Bus,
    truck: Truck,
    pickaxe: Pickaxe,
    factory: Factory,
    "hard-hat": HardHat,
    wheat: Wheat,
    "shield-alert": ShieldAlert,
    "shield-half": ShieldHalf,
};

function normalize(text: string): string {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

export const TOOL_LABELS: Record<string, string> = {
    book_appointment: "Prise de rendez-vous",
    send_message: "SMS / WhatsApp / e-mail",
    create_ticket: "Tickets",
    schedule_callback: "Rappel",
    transfer_call: "Transfert d'appel",
};

export function TemplateGallery({
    templates,
    selected,
    onOpen,
    searchable = true,
}: {
    templates: TemplateSummary[];
    selected: string;
    onOpen: (template: TemplateSummary) => void;
    searchable?: boolean;
}) {
    const [query, setQuery] = useState("");
    const groups = useMemo(() => {
        const q = searchable ? normalize(query.trim()) : "";
        const visible = q
            ? templates.filter((t) =>
                  normalize([t.label, t.description, t.sector_label, t.activity].join(" ")).includes(q),
              )
            : templates;
        const bySector = new Map<string, { label: string; items: TemplateSummary[] }>();
        for (const t of visible) {
            const group = bySector.get(t.sector) ?? { label: t.sector_label, items: [] };
            group.items.push(t);
            bySector.set(t.sector, group);
        }
        return [...bySector.values()];
    }, [templates, query, searchable]);

    return (
        <div className="space-y-5">
            {searchable && (
            <div className="relative max-w-sm">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                    className="pl-9"
                    placeholder="Rechercher un métier (banque, mine, énergie…)"
                    aria-label="Rechercher un métier"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </div>
            )}
            {groups.length === 0 && <p className="text-sm text-muted-foreground">Aucun métier ne correspond.</p>}
            {groups.map((group) => (
                <section key={group.label} data-testid="sector-group">
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {group.label}
                    </h3>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        {group.items.map((template) => {
                            const Icon = TEMPLATE_ICONS[template.icon] ?? Building2;
                            const active = template.id === selected;
                            return (
                                <button
                                    key={template.id}
                                    type="button"
                                    data-testid={`template-${template.id}`}
                                    onClick={() => onOpen(template)}
                                    className={cn(
                                        "group relative flex flex-col gap-2 rounded-xl border p-4 text-left transition-colors hover:border-brand-cyan/60 hover:bg-muted/30",
                                        active ? "border-brand-cyan/70 bg-brand-cyan/5" : "border-border/60",
                                    )}
                                >
                                    <span className="flex items-center gap-2">
                                        <span
                                            className={cn(
                                                "flex size-9 shrink-0 items-center justify-center rounded-lg",
                                                active
                                                    ? "bg-gradient-to-br from-brand-cyan to-brand-violet text-white"
                                                    : "bg-muted text-muted-foreground group-hover:text-foreground",
                                            )}
                                        >
                                            <Icon className="size-4" />
                                        </span>
                                        <span className="font-medium leading-tight">{template.label}</span>
                                    </span>
                                    <span className="text-sm text-muted-foreground">{template.description}</span>
                                    {(active || template.rules.length > 0) && (
                                        <span className="mt-auto flex flex-wrap gap-1">
                                            {active && (
                                                <Badge className="w-fit whitespace-nowrap" variant="secondary">
                                                    <Check className="size-3" /> Votre métier
                                                </Badge>
                                            )}
                                            {template.rules.length > 0 && (
                                                <Badge variant="outline" className="w-fit whitespace-nowrap text-[10px]">
                                                    <ShieldAlert className="size-3" /> {template.rules.length} règle
                                                    {template.rules.length > 1 ? "s" : ""} impérative
                                                    {template.rules.length > 1 ? "s" : ""}
                                                </Badge>
                                            )}
                                        </span>
                                    )}
                                </button>
                            );
                        })}
                    </div>
                </section>
            ))}
        </div>
    );
}

export function TemplateDialog({
    template,
    isCurrent,
    onClose,
    onApply,
    onCreateAgent,
    skillLabels,
}: {
    template: TemplateSummary | null;
    isCurrent: boolean;
    onClose: () => void;
    onApply: (template: TemplateSummary, withExamples: boolean) => Promise<void>;
    onCreateAgent: (template: TemplateSummary) => Promise<void>;
    skillLabels: Record<string, string>;
}) {
    const [withExamples, setWithExamples] = useState(true);
    const [busy, setBusy] = useState<"apply" | "agent" | null>(null);
    if (!template) return null;
    const Icon = TEMPLATE_ICONS[template.icon] ?? Building2;

    const run = async (what: "apply" | "agent") => {
        setBusy(what);
        try {
            if (what === "apply") await onApply(template, withExamples);
            else await onCreateAgent(template);
        } finally {
            setBusy(null);
        }
    };
    const examples = template.example_offers.length + template.example_faq.length + template.example_policies.length;

    return (
        <Dialog open onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
                <DialogHeader className="min-w-0">
                    <DialogTitle className="flex items-center gap-2">
                        <Icon className="size-5" /> {template.label}
                    </DialogTitle>
                    <DialogDescription>
                        {template.sector_label} · {template.description}
                    </DialogDescription>
                </DialogHeader>
                <div className="min-w-0 space-y-4 text-sm">
                    {template.rules.length > 0 && (
                        <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
                            <h3 className="mb-1 flex items-center gap-1.5 font-semibold">
                                <ShieldAlert className="size-4 text-amber-400" /> Règles impératives
                            </h3>
                            <p className="mb-1 text-xs text-muted-foreground">
                                Données à l&apos;agent avant tout le reste : elles priment sur toute demande.
                            </p>
                            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                                {template.rules.map((rule) => (
                                    <li key={rule}>{rule}</li>
                                ))}
                            </ul>
                        </section>
                    )}
                    <section>
                        <h3 className="mb-1 font-semibold">Méthode de l&apos;agent</h3>
                        <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                            {template.method.map((step) => (
                                <li key={step}>{step}</li>
                            ))}
                        </ol>
                    </section>
                    <section>
                        <h3 className="mb-1 font-semibold">Ce qu&apos;il recueille</h3>
                        <div className="flex flex-wrap gap-1">
                            {template.collects.map((item) => (
                                <Badge key={item} variant="outline">
                                    {item}
                                </Badge>
                            ))}
                        </div>
                    </section>
                    <section className="grid gap-4 sm:grid-cols-2">
                        <div>
                            <h3 className="mb-1 font-semibold">Compétences activées</h3>
                            <ul className="space-y-0.5 text-muted-foreground">
                                {template.skills.map((skill) => (
                                    <li key={skill} className="flex items-center gap-1.5">
                                        <Check className="size-3.5 text-emerald-400" /> {skillLabels[skill] ?? skill}
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h3 className="mb-1 font-semibold">Issues classées</h3>
                            <p className="text-muted-foreground">{template.dispositions.join(", ")}</p>
                            <h3 className="mb-1 mt-3 font-semibold">Outils conseillés</h3>
                            <p className="text-muted-foreground">
                                {template.tools.map((t) => TOOL_LABELS[t] ?? t).join(", ")}
                            </p>
                        </div>
                    </section>
                    {template.recommendations.length > 0 && (
                        <section>
                            <h3 className="mb-1 flex items-center gap-1.5 font-semibold">
                                <Lightbulb className="size-4 text-brand-cyan" /> Pour bien démarrer
                            </h3>
                            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                                {template.recommendations.map((tip) => (
                                    <li key={tip}>{tip}</li>
                                ))}
                            </ul>
                        </section>
                    )}
                    {examples > 0 && (
                        <div className="flex items-start gap-2 rounded-lg border border-border/60 p-3">
                            <Checkbox
                                id="with-examples"
                                checked={withExamples}
                                onCheckedChange={(v) => setWithExamples(v === true)}
                            />
                            <Label htmlFor="with-examples" className="font-normal leading-snug">
                                Pré-remplir les offres, la FAQ et les conditions encore vides avec {examples} exemples à
                                adapter (rien de ce que vous avez saisi n&apos;est remplacé).
                            </Label>
                        </div>
                    )}
                </div>
                <DialogFooter className="gap-2">
                    <Button variant="outline" onClick={() => run("agent")} disabled={busy !== null}>
                        <Bot /> Créer l&apos;agent {template.label.toLowerCase()}
                    </Button>
                    <Button onClick={() => run("apply")} disabled={busy !== null}>
                        <Check /> {isCurrent ? "Réappliquer ce métier" : "Choisir ce métier"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

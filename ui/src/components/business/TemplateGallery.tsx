"use client";

import {
    BedDouble,
    Bot,
    Building2,
    Check,
    GraduationCap,
    Home,
    type LucideIcon,
    ShieldCheck,
    ShoppingBag,
    Stethoscope,
} from "lucide-react";
import { useState } from "react";

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
};

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
}: {
    templates: TemplateSummary[];
    selected: string;
    onOpen: (template: TemplateSummary) => void;
}) {
    return (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {templates.map((template) => {
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
                                    "flex size-9 items-center justify-center rounded-lg",
                                    active
                                        ? "bg-gradient-to-br from-brand-cyan to-brand-violet text-white"
                                        : "bg-muted text-muted-foreground group-hover:text-foreground",
                                )}
                            >
                                <Icon className="size-4" />
                            </span>
                            <span className="font-medium">{template.label}</span>
                        </span>
                        <span className="text-sm text-muted-foreground">{template.description}</span>
                        {active && (
                            <Badge className="mt-auto w-fit whitespace-nowrap" variant="secondary">
                                <Check className="size-3" /> Votre métier
                            </Badge>
                        )}
                    </button>
                );
            })}
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
                    <DialogDescription>{template.description}</DialogDescription>
                </DialogHeader>
                <div className="min-w-0 space-y-4 text-sm">
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

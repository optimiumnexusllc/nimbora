"use client";

import { ArrowDown, Bot, Hash, Loader2, Plus, Trash2, Volume2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { previewPromptApiV1PbxPromptsPreviewPost } from "@/client/sdk.gen";
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
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import {
    describeDestination,
    type Destination,
    DestinationPicker,
    type DestinationSources,
    type DestinationType,
} from "./DestinationPicker";
import type { MenuSpecShape } from "./types";

export const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];
const KEY_WORDS: Record<string, string> = { "*": "étoile", "#": "dièse" };

export function spokenMenu(spec: MenuSpecShape): string {
    if (spec.menu_text.trim()) return spec.menu_text.trim();
    return spec.choices
        .filter((c) => c.label.trim())
        .map((c) => {
            const label = c.label.trim();
            return `Pour ${label[0].toLowerCase()}${label.slice(1)}, tapez ${KEY_WORDS[c.digit] ?? c.digit}.`;
        })
        .join(" ");
}

export const EMPTY_SPEC: MenuSpecShape = {
    greeting_text: "",
    menu_text: "",
    invalid_text: "Ce choix n'est pas valide.",
    choices: [{ digit: "1", label: "", type: "hangup", target_id: null }],
    timeout_seconds: 5,
    max_tries: 3,
    fallback: { type: "hangup", target_id: null },
    voice_workflow_id: null,
};

function problems(name: string, spec: MenuSpecShape): string | null {
    if (!name.trim()) return "Donnez un nom au menu.";
    if (spec.choices.length === 0) return "Ajoutez au moins un choix.";
    for (const c of spec.choices) {
        if (!c.label.trim()) return `Touche ${c.digit} : décrivez le choix (ce que l'appelant entend).`;
        if (c.type !== "hangup" && c.target_id == null) return `Touche ${c.digit} : choisissez la destination.`;
    }
    if (spec.fallback.type !== "hangup" && spec.fallback.target_id == null) return "Choisissez la destination sans réponse.";
    return null;
}

function PreviewButton({ text, voiceWorkflowId, label }: { text: string; voiceWorkflowId: number | null; label: string }) {
    const [loading, setLoading] = useState(false);
    return (
        <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!text.trim() || loading}
            aria-label={label}
            onClick={async () => {
                setLoading(true);
                const response = await previewPromptApiV1PbxPromptsPreviewPost({
                    body: { text, voice_workflow_id: voiceWorkflowId },
                    parseAs: "blob",
                });
                setLoading(false);
                if (response.error || !(response.data instanceof Blob)) {
                    toast.error(detailFromError(response.error, "Écoute impossible"));
                    return;
                }
                const url = URL.createObjectURL(response.data);
                const audio = new Audio(url);
                audio.onended = () => URL.revokeObjectURL(url);
                void audio.play().catch(() => toast.error("Lecture bloquée par le navigateur"));
            }}
        >
            {loading ? <Loader2 className="animate-spin" /> : <Volume2 />} Écouter
        </Button>
    );
}

/** The menu as the caller lives it: message, keypad, destinations. */
export function MenuFlow({ name, spec, sources }: { name: string; spec: MenuSpecShape; sources: DestinationSources }) {
    const byKey = new Map(spec.choices.map((c) => [c.digit, c]));
    return (
        <div className="space-y-3 rounded-xl border border-border/60 bg-muted/20 p-4" data-testid="menu-flow">
            <div className="rounded-lg border border-border/60 bg-background/60 p-3 text-sm">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Appel entrant · {name || "Menu"}</p>
                {spec.greeting_text.trim() && <p className="mt-1 italic">« {spec.greeting_text.trim()} »</p>}
                <p className="mt-1 italic text-muted-foreground">« {spokenMenu(spec) || "…"} »</p>
            </div>
            <ArrowDown className="mx-auto size-4 text-muted-foreground" />
            <div className="mx-auto grid w-fit grid-cols-3 gap-1.5" aria-label="Clavier du téléphone">
                {KEYS.map((key) => {
                    const choice = byKey.get(key);
                    return (
                        <div
                            key={key}
                            title={choice?.label}
                            className={cn(
                                "flex size-10 items-center justify-center rounded-full border font-mono text-sm",
                                choice
                                    ? choice.type === "ai"
                                        ? "border-brand-cyan bg-brand-cyan/15 text-brand-cyan"
                                        : "border-brand-violet bg-brand-violet/15"
                                    : "border-border/40 text-muted-foreground/40",
                            )}
                        >
                            {key}
                        </div>
                    );
                })}
            </div>
            <ul className="space-y-1 text-sm">
                {spec.choices.map((c) => (
                    <li key={c.digit} className="flex min-w-0 items-start gap-2">
                        <Badge variant="outline" className="mt-0.5 font-mono">
                            {c.digit}
                        </Badge>
                        <span className="min-w-0">
                            <span className="block break-words">{c.label || "—"}</span>
                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                {c.type === "ai" && <Bot className="size-3.5 shrink-0 text-brand-cyan" />}
                                {describeDestination(c as Destination, sources)}
                            </span>
                        </span>
                    </li>
                ))}
                <li className="flex items-center gap-2 border-t border-border/40 pt-1 text-xs text-muted-foreground">
                    Sans choix après {spec.max_tries} essai{spec.max_tries > 1 ? "s" : ""} ·{" "}
                    {describeDestination(spec.fallback as Destination, sources)}
                </li>
            </ul>
        </div>
    );
}

export function MenuEditor({
    open,
    onOpenChange,
    initial,
    menuId,
    sources,
    onSave,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    initial: { name: string; spec: MenuSpecShape };
    menuId?: number;
    sources: DestinationSources;
    onSave: (name: string, spec: MenuSpecShape, publish: boolean) => Promise<boolean>;
}) {
    const [name, setName] = useState(initial.name);
    const [spec, setSpec] = useState<MenuSpecShape>(initial.spec);
    const [saving, setSaving] = useState(false);
    const set = (patch: Partial<MenuSpecShape>) => setSpec((s) => ({ ...s, ...patch }));
    const freeKeys = KEYS.filter((k) => !spec.choices.some((c) => c.digit === k));
    const issue = problems(name, spec);

    const submit = async (publish: boolean) => {
        setSaving(true);
        const ok = await onSave(name.trim(), spec, publish);
        setSaving(false);
        if (ok) onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
                <DialogHeader>
                    <DialogTitle>{menuId ? `Modifier « ${initial.name} »` : "Nouveau serveur vocal"}</DialogTitle>
                    <DialogDescription>
                        Les messages sont prononcés avec la voix de votre organisation (ou celle d&apos;un agent) et
                        publiés sur le PBX. Chaque touche peut mener à une file, un poste, une messagerie, un autre menu
                        — ou directement à un agent IA.
                    </DialogDescription>
                </DialogHeader>

                <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
                    <div className="min-w-0 space-y-5">
                        <div className="grid gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                                <Label htmlFor="menu-name">Nom</Label>
                                <Input id="menu-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Accueil" />
                            </div>
                            <div className="space-y-1">
                                <Label>Voix</Label>
                                <Select
                                    value={spec.voice_workflow_id ? String(spec.voice_workflow_id) : "org"}
                                    onValueChange={(v) => set({ voice_workflow_id: v === "org" ? null : Number(v) })}
                                >
                                    <SelectTrigger aria-label="Voix" className="w-full">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="org">Voix par défaut de l&apos;organisation</SelectItem>
                                        {sources.workflows.map((w) => (
                                            <SelectItem key={w.id} value={String(w.id)}>
                                                Voix de l&apos;agent « {w.name} »
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>

                        <div className="space-y-1">
                            <div className="flex items-center justify-between">
                                <Label htmlFor="menu-greeting">Message d&apos;accueil (facultatif)</Label>
                                <PreviewButton text={spec.greeting_text} voiceWorkflowId={spec.voice_workflow_id} label="Écouter l'accueil" />
                            </div>
                            <Textarea
                                id="menu-greeting"
                                rows={2}
                                maxLength={600}
                                value={spec.greeting_text}
                                onChange={(e) => set({ greeting_text: e.target.value })}
                                placeholder="Bienvenue chez … Cet appel peut être enregistré."
                            />
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label>Choix au clavier</Label>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={freeKeys.length === 0 || spec.choices.length >= 12}
                                    onClick={() =>
                                        set({ choices: [...spec.choices, { digit: freeKeys[0], label: "", type: "hangup", target_id: null }] })
                                    }
                                >
                                    <Plus /> Ajouter un choix
                                </Button>
                            </div>
                            {spec.choices.map((choice, index) => (
                                <div
                                    key={index}
                                    className="grid min-w-0 grid-cols-[72px_minmax(0,1fr)_36px] items-center gap-2 rounded-lg border border-border/60 p-2"
                                    data-testid="menu-choice"
                                >
                                    <Select
                                        value={choice.digit}
                                        onValueChange={(digit) =>
                                            set({ choices: spec.choices.map((c, i) => (i === index ? { ...c, digit } : c)) })
                                        }
                                    >
                                        <SelectTrigger aria-label={`Touche du choix ${index + 1}`} className="w-full font-mono">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {[choice.digit, ...freeKeys].sort((a, b) => KEYS.indexOf(a) - KEYS.indexOf(b)).map((k) => (
                                                <SelectItem key={k} value={k} className="font-mono">
                                                    {k}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Input
                                        aria-label={`Libellé du choix ${index + 1}`}
                                        placeholder="Le service commercial"
                                        maxLength={80}
                                        value={choice.label}
                                        onChange={(e) =>
                                            set({ choices: spec.choices.map((c, i) => (i === index ? { ...c, label: e.target.value } : c)) })
                                        }
                                    />
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        aria-label={`Retirer le choix ${index + 1}`}
                                        disabled={spec.choices.length === 1}
                                        onClick={() => set({ choices: spec.choices.filter((_, i) => i !== index) })}
                                    >
                                        <Trash2 />
                                    </Button>
                                    <DestinationPicker
                                        className="col-span-3 sm:grid-cols-[180px_minmax(0,1fr)]"
                                        label={`Destination du choix ${index + 1}`}
                                        value={{ type: choice.type as DestinationType, target_id: choice.target_id }}
                                        sources={sources}
                                        excludeMenuId={menuId}
                                        onChange={(d) =>
                                            set({ choices: spec.choices.map((c, i) => (i === index ? { ...c, ...d } : c)) })
                                        }
                                    />
                                </div>
                            ))}
                        </div>

                        <div className="space-y-1">
                            <div className="flex items-center justify-between">
                                <Label htmlFor="menu-text">Message du menu</Label>
                                <PreviewButton text={spokenMenu(spec)} voiceWorkflowId={spec.voice_workflow_id} label="Écouter le menu" />
                            </div>
                            <Textarea
                                id="menu-text"
                                rows={2}
                                maxLength={800}
                                value={spec.menu_text}
                                onChange={(e) => set({ menu_text: e.target.value })}
                                placeholder={spokenMenu({ ...spec, menu_text: "" }) || "Écrit automatiquement à partir des choix"}
                            />
                            <p className="text-xs text-muted-foreground">Laissez vide : le texte est écrit à partir des choix.</p>
                        </div>

                        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px_120px]">
                            <div className="space-y-1">
                                <Label htmlFor="menu-invalid">Message si la touche n&apos;existe pas</Label>
                                <Input
                                    id="menu-invalid"
                                    maxLength={300}
                                    value={spec.invalid_text}
                                    onChange={(e) => set({ invalid_text: e.target.value })}
                                />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="menu-timeout">Attente (s)</Label>
                                <Input
                                    id="menu-timeout"
                                    type="number"
                                    min={2}
                                    max={30}
                                    value={spec.timeout_seconds}
                                    onChange={(e) => set({ timeout_seconds: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="menu-tries">Essais</Label>
                                <Input
                                    id="menu-tries"
                                    type="number"
                                    min={1}
                                    max={5}
                                    value={spec.max_tries}
                                    onChange={(e) => set({ max_tries: Number(e.target.value) })}
                                />
                            </div>
                        </div>

                        <div className="space-y-1">
                            <Label className="flex items-center gap-1.5">
                                <Hash className="size-3.5" /> Sans choix valide
                            </Label>
                            <DestinationPicker
                                label="Destination sans choix"
                                value={spec.fallback as Destination}
                                sources={sources}
                                excludeMenuId={menuId}
                                onChange={(fallback) => set({ fallback })}
                            />
                            <p className="text-xs text-muted-foreground">
                                Conseil : un agent IA ici, et personne ne raccroche sans réponse.
                            </p>
                        </div>
                    </div>

                    <MenuFlow name={name} spec={spec} sources={sources} />
                </div>

                <DialogFooter className="items-center gap-2">
                    {issue && <p className="mr-auto text-sm text-amber-400">{issue}</p>}
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button variant="outline" disabled={Boolean(issue) || saving} onClick={() => void submit(false)}>
                        Enregistrer le brouillon
                    </Button>
                    <Button disabled={Boolean(issue) || saving} onClick={() => void submit(true)}>
                        {saving && <Loader2 className="animate-spin" />} Enregistrer et publier
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

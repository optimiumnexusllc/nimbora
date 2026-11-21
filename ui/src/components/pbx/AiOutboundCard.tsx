"use client";

import { Bot, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { readAiOutboundApiV1PbxAiOutboundGet, saveAiOutboundApiV1PbxAiOutboundPut } from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";

import type { PbxTrunk } from "./types";

export type AiOutboundSettings = {
    mode: "routes" | "trunk" | "custom";
    trunk_id: number | null;
    dial_string_template: string;
    number_format: "as_is" | "international_00" | "national";
    country_code: string;
    national_prefix: string;
    caller_id: string | null;
    example: { number: string; dial_string: string };
};

type Form = {
    mode: "routes" | "trunk";
    trunk_id: string;
    number_format: AiOutboundSettings["number_format"];
    country_code: string;
    national_prefix: string;
    caller_id: string;
};

/** Mirrors the backend's rewrite, for an instant preview while editing. */
export function previewNumber(number: string, form: Pick<Form, "number_format" | "country_code" | "national_prefix">): string {
    if (!number.startsWith("+") || form.number_format === "as_is") return number;
    const digits = number.replace(/\D/g, "");
    const cc = form.country_code.replace(/\D/g, "");
    if (form.number_format === "national" && cc && digits.startsWith(cc)) return `${form.national_prefix}${digits.slice(cc.length)}`;
    return `00${digits}`;
}

export function AiOutboundCard({ trunks, hasRoutes }: { trunks: PbxTrunk[]; hasRoutes: boolean }) {
    const [settings, setSettings] = useState<AiOutboundSettings | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [form, setForm] = useState<Form | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        void (async () => {
            const response = await readAiOutboundApiV1PbxAiOutboundGet();
            if (response.error || !response.data) {
                setError(detailFromError(response.error, "Indisponible"));
                return;
            }
            const data = response.data as unknown as AiOutboundSettings;
            setSettings(data);
            setForm({
                mode: data.mode === "trunk" ? "trunk" : "routes",
                trunk_id: data.trunk_id ? String(data.trunk_id) : "",
                number_format: data.number_format,
                country_code: data.country_code,
                national_prefix: data.national_prefix,
                caller_id: data.caller_id ?? "",
            });
        })();
    }, []);

    const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f));
    const example = "+2250707112233";
    const trunkId = form?.trunk_id || (trunks[0] ? String(trunks[0].id) : "");
    const trunkName = trunks.find((t) => String(t.id) === trunkId)?.label;

    return (
        <PageSection
            title={
                <span className="flex items-center gap-2">
                    <Bot className="size-5 text-brand-cyan" /> Appels sortants des agents IA
                </span>
            }
            description="Campagnes, rappels et appels de test des agents IA partent par les lignes de votre PBX, avec votre numéro."
        >
            {error && <p className="text-sm text-muted-foreground">{error}</p>}
            {form && settings && (
                <div className="space-y-4" data-testid="ai-outbound">
                    {settings.mode === "custom" && (
                        <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
                            Réglage actuel personnalisé : <code>{settings.dial_string_template}</code>. Enregistrer le remplace.
                        </p>
                    )}
                    <RadioGroup value={form.mode} onValueChange={(v) => set({ mode: v as Form["mode"] })} className="grid gap-2 md:grid-cols-2">
                        <label className="flex cursor-pointer gap-3 rounded-lg border border-border/60 p-3 has-[[data-state=checked]]:border-brand-cyan">
                            <RadioGroupItem value="routes" aria-label="Par les routes sortantes" disabled={!hasRoutes} />
                            <span className="text-sm">
                                <span className="font-medium">Par les routes sortantes</span>
                                <span className="block text-muted-foreground">
                                    Comme un poste : motifs, numéro présenté et relais entre lignes.
                                    {!hasRoutes && " Créez d'abord une route."}
                                </span>
                            </span>
                        </label>
                        <label className="flex cursor-pointer gap-3 rounded-lg border border-border/60 p-3 has-[[data-state=checked]]:border-brand-cyan">
                            <RadioGroupItem value="trunk" aria-label="Par une ligne précise" disabled={trunks.length === 0} />
                            <span className="text-sm">
                                <span className="font-medium">Par une ligne précise</span>
                                <span className="block text-muted-foreground">Directement vers l&apos;opérateur, sans passer par les routes.</span>
                            </span>
                        </label>
                    </RadioGroup>
                    <div className="grid gap-3 md:grid-cols-4">
                        {form.mode === "trunk" && (
                            <div className="space-y-1">
                                <Label>Ligne</Label>
                                <Select value={trunkId} onValueChange={(v) => set({ trunk_id: v })}>
                                    <SelectTrigger aria-label="Ligne" className="w-full">
                                        <SelectValue placeholder="Choisir" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {trunks.map((t) => (
                                            <SelectItem key={t.id} value={String(t.id)}>
                                                {t.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}
                        <div className="space-y-1">
                            <Label>Format du numéro composé</Label>
                            <Select value={form.number_format} onValueChange={(v) => set({ number_format: v as Form["number_format"] })}>
                                <SelectTrigger aria-label="Format du numéro composé" className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="as_is">Inchangé (+225…)</SelectItem>
                                    <SelectItem value="international_00">Préfixe 00 (00225…)</SelectItem>
                                    <SelectItem value="national">National (07…)</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        {form.number_format === "national" && (
                            <>
                                <div className="space-y-1">
                                    <Label htmlFor="ai-cc">Indicatif du pays</Label>
                                    <Input id="ai-cc" placeholder="225" value={form.country_code} onChange={(e) => set({ country_code: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="ai-prefix">Préfixe national</Label>
                                    <Input id="ai-prefix" placeholder="vide, ou 0" value={form.national_prefix} onChange={(e) => set({ national_prefix: e.target.value })} />
                                </div>
                            </>
                        )}
                        <div className="space-y-1">
                            <Label htmlFor="ai-caller-id">Numéro présenté</Label>
                            <Input id="ai-caller-id" placeholder="+225 27 22 00 00 00" value={form.caller_id} onChange={(e) => set({ caller_id: e.target.value })} />
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                        <p className="mr-auto text-sm text-muted-foreground" data-testid="ai-outbound-preview">
                            Un appel IA vers <span className="font-mono">{example}</span> compose{" "}
                            <span className="font-mono text-foreground">{previewNumber(example, form)}</span>{" "}
                            {form.mode === "routes" ? "via les routes sortantes" : `sur ${trunkName ?? "la ligne choisie"}`}
                            {form.caller_id.trim() && `, présenté ${form.caller_id.trim()}`}.
                        </p>
                        <Button
                            disabled={saving || (form.mode === "trunk" && !trunkId) || (form.mode === "routes" && !hasRoutes)}
                            onClick={async () => {
                                setSaving(true);
                                const response = await saveAiOutboundApiV1PbxAiOutboundPut({
                                    body: {
                                        mode: form.mode,
                                        trunk_id: form.mode === "trunk" ? Number(trunkId) : null,
                                        number_format: form.number_format,
                                        country_code: form.country_code,
                                        national_prefix: form.national_prefix,
                                        caller_id: form.caller_id.trim() || null,
                                    },
                                });
                                setSaving(false);
                                if (response.error || !response.data) {
                                    toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                    return;
                                }
                                setSettings(response.data as unknown as AiOutboundSettings);
                                toast.success("Les agents IA appellent désormais par le PBX");
                            }}
                        >
                            <Save /> Enregistrer
                        </Button>
                    </div>
                </div>
            )}
        </PageSection>
    );
}

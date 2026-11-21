"use client";

import { Clock, Eye, Save, Store } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    applyTemplateApiV1BusinessTemplatesTemplateIdApplyPost,
    createAgentApiV1BusinessTemplatesTemplateIdAgentPost,
    listSkillsApiV1BusinessSkillsGet,
    listTemplatesApiV1BusinessTemplatesGet,
    previewProfileApiV1BusinessProfilePreviewPost,
    readProfileApiV1BusinessProfileGet,
    updateProfileApiV1BusinessProfilePut,
} from "@/client/sdk.gen";
import type { ProfilePreview, Skills, TemplateSummary } from "@/client/types.gen";
import { EmergencyEditor, FaqEditor, OffersEditor, PoliciesEditor } from "@/components/business/ContentEditors";
import { ClosuresEditor, HoursEditor } from "@/components/business/HoursEditor";
import {
    cleanProfile,
    normalizeProfile,
    type Profile,
    SKILL_DESCRIPTIONS,
    TIMEZONES,
} from "@/components/business/profile";
import { TemplateDialog, TemplateGallery, TOOL_LABELS } from "@/components/business/TemplateGallery";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

function Field({
    id,
    label,
    hint,
    children,
}: {
    id: string;
    label: string;
    hint?: string;
    children: React.ReactNode;
}) {
    return (
        <div className="space-y-1">
            <Label htmlFor={id}>{label}</Label>
            {children}
            {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
    );
}

export default function BusinessPage() {
    const { user, loading: authLoading } = useAuth();
    const router = useRouter();
    const [profile, setProfile] = useState<Profile | null>(null);
    const [saved, setSaved] = useState<string>("");
    const [templates, setTemplates] = useState<TemplateSummary[]>([]);
    const [skillLabels, setSkillLabels] = useState<Record<string, string>>({});
    const [openTemplate, setOpenTemplate] = useState<TemplateSummary | null>(null);
    const [showAllTrades, setShowAllTrades] = useState<boolean | null>(null);
    const [tab, setTab] = useState("identity");
    const [preview, setPreview] = useState<ProfilePreview | null>(null);
    const [saving, setSaving] = useState(false);
    const fetched = useRef(false);

    const adopt = useCallback((data: Parameters<typeof normalizeProfile>[0]) => {
        const next = normalizeProfile(data);
        setProfile(next);
        setSaved(JSON.stringify(cleanProfile(next)));
    }, []);

    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void (async () => {
            const [p, t, s] = await Promise.all([
                readProfileApiV1BusinessProfileGet(),
                listTemplatesApiV1BusinessTemplatesGet(),
                listSkillsApiV1BusinessSkillsGet(),
            ]);
            if (p.error) {
                toast.error(detailFromError(p.error, "Impossible de charger la fiche"));
                return;
            }
            adopt(p.data);
            setTemplates(t.data ?? []);
            setSkillLabels(Object.fromEntries((s.data ?? []).map((x) => [x.id, x.label])));
        })();
    }, [authLoading, user, adopt]);

    const dirty = profile !== null && JSON.stringify(cleanProfile(profile)) !== saved;

    const loadPreview = useCallback(async (current: Profile) => {
        const response = await previewProfileApiV1BusinessProfilePreviewPost({ body: cleanProfile(current) });
        if (response.error) {
            setPreview(null);
            toast.error(detailFromError(response.error, "Aperçu indisponible"));
            return;
        }
        setPreview(response.data ?? null);
    }, []);

    useEffect(() => {
        if (tab !== "preview" || !profile) return;
        const timer = setTimeout(() => void loadPreview(profile), 300);
        return () => clearTimeout(timer);
    }, [tab, profile, loadPreview]);

    if (!profile) {
        return (
            <PageLayout title="Mon entreprise">
                <Skeleton className="h-96 w-full" />
            </PageLayout>
        );
    }

    const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setProfile({ ...profile, [key]: value });
    const text = (key: keyof Profile) => ({
        id: `b-${key}`,
        value: (profile[key] as string) ?? "",
        onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
            set(key, e.target.value as Profile[typeof key]),
    });

    const save = async () => {
        setSaving(true);
        const response = await updateProfileApiV1BusinessProfilePut({ body: cleanProfile(profile) });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        adopt(response.data);
        toast.success("Fiche enregistrée : tous vos agents l'utilisent dès le prochain échange");
    };

    const applyTemplate = async (template: TemplateSummary, withExamples: boolean) => {
        if (dirty) {
            toast.error("Enregistrez d'abord vos modifications");
            return;
        }
        const response = await applyTemplateApiV1BusinessTemplatesTemplateIdApplyPost({
            path: { template_id: template.id },
            body: { with_examples: withExamples },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Impossible d'appliquer ce métier"));
            return;
        }
        adopt(response.data);
        setOpenTemplate(null);
        toast.success(`Métier « ${template.label} » appliqué`);
    };

    const createAgent = async (template: TemplateSummary) => {
        if (dirty) {
            toast.error("Enregistrez d'abord vos modifications");
            return;
        }
        const response = await createAgentApiV1BusinessTemplatesTemplateIdAgentPost({
            path: { template_id: template.id },
            body: {},
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Création de l'agent impossible"));
            return;
        }
        const created = response.data;
        setOpenTemplate(null);
        const missing = created.missing_tools.map((t) => TOOL_LABELS[t] ?? t);
        toast.success(`Agent « ${created.name} » créé`, {
            description: missing.length
                ? `Pour qu'il agisse, ajoutez ces outils : ${missing.join(", ")}.`
                : "Les outils de votre entreprise y sont déjà rattachés.",
            action: { label: "Ouvrir", onClick: () => router.push(`/workflow/${created.workflow_id}`) },
            duration: 10000,
        });
    };

    return (
        <PageLayout
            title="Mon entreprise"
            description="La fiche que lisent tous vos agents, au téléphone, sur WhatsApp et sur le chat web : identité, horaires, offres, FAQ et compétences."
            actions={
                <>
                    <div className="flex items-center gap-2 rounded-lg border border-border/60 px-3 py-1.5">
                        <Switch
                            id="b-enabled"
                            checked={profile.enabled}
                            onCheckedChange={(v) => set("enabled", v)}
                            aria-label="Donner la fiche aux agents"
                        />
                        <Label htmlFor="b-enabled" className="text-sm font-normal">
                            Donnée aux agents
                        </Label>
                    </div>
                    <Button onClick={save} disabled={!dirty || saving}>
                        <Save /> {dirty ? "Enregistrer" : "Enregistré"}
                    </Button>
                </>
            }
        >
            <PageSection
                title={
                    <span className="flex items-center gap-2">
                        <Store className="size-5" /> Votre métier
                    </span>
                }
                description="25 métiers dans 8 secteurs. Chacun apporte ses règles impératives (sécurité, conformité), sa méthode, les données à recueillir, les compétences utiles et un agent prêt à l'emploi."
            >
                {(() => {
                    // Once a trade is chosen, show it alone; the catalogue opens on demand.
                    const expanded = showAllTrades ?? profile.industry === "general";
                    const current = templates.filter((t) => t.id === profile.industry);
                    return (
                        <div className="space-y-3">
                            <TemplateGallery
                                templates={expanded ? templates : current}
                                selected={profile.industry}
                                onOpen={setOpenTemplate}
                                searchable={expanded}
                            />
                            <Button variant="outline" size="sm" onClick={() => setShowAllTrades(!expanded)}>
                                {expanded ? "Masquer les autres métiers" : `Voir les ${templates.length} métiers`}
                            </Button>
                        </div>
                    );
                })()}
            </PageSection>

            <Tabs value={tab} onValueChange={setTab} className="space-y-4">
                <TabsList className="flex-wrap">
                    <TabsTrigger value="identity">Identité</TabsTrigger>
                    <TabsTrigger value="hours">Horaires et lieu</TabsTrigger>
                    <TabsTrigger value="content">Offres et FAQ</TabsTrigger>
                    <TabsTrigger value="skills">Compétences</TabsTrigger>
                    <TabsTrigger value="preview">
                        <Eye className="size-4" /> Ce que lisent les agents
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="identity" className="grid gap-4 rounded-xl border border-border/60 p-5 md:grid-cols-2">
                    <Field id="b-name" label="Nom de l'entreprise">
                        <Input {...text("name")} placeholder="Ivoire Immo" />
                    </Field>
                    <Field id="b-activity" label="Activité" hint="En quelques mots : agence immobilière, boulangerie…">
                        <Input {...text("activity")} />
                    </Field>
                    <Field id="b-assistant_name" label="Prénom de l'assistant" hint="Utilisé quand l'agent se présente.">
                        <Input {...text("assistant_name")} placeholder="Sarah" />
                    </Field>
                    <Field id="b-tone" label="Ton">
                        <Input {...text("tone")} placeholder="chaleureux et professionnel" />
                    </Field>
                    <div className="md:col-span-2">
                        <Field id="b-description" label="Présentation">
                            <Textarea
                                {...text("description")}
                                rows={3}
                                placeholder="Qui vous êtes, ce que vous proposez, ce qui vous distingue."
                            />
                        </Field>
                    </div>
                    <Field id="b-phone" label="Téléphone">
                        <Input {...text("phone")} />
                    </Field>
                    <Field id="b-whatsapp" label="WhatsApp">
                        <Input {...text("whatsapp")} />
                    </Field>
                    <Field id="b-email" label="E-mail">
                        <Input {...text("email")} type="email" />
                    </Field>
                    <Field id="b-website" label="Site web">
                        <Input {...text("website")} />
                    </Field>
                    <div className="space-y-2 md:col-span-2">
                        <Label>Numéros d&apos;urgence</Label>
                        <p className="text-xs text-muted-foreground">
                            Donnés en priorité par l&apos;agent en cas de danger ou d&apos;urgence (dépannage, SAMU,
                            opposition carte, sécurité du site…). Vérifiez-les : un numéro erroné peut avoir des
                            conséquences graves.
                        </p>
                        <EmergencyEditor
                            contacts={profile.emergency_contacts}
                            onChange={(v) => set("emergency_contacts", v)}
                        />
                    </div>
                    <div className="md:col-span-2">
                        <Field id="b-languages" label="Langues parlées" hint="Séparées par des virgules.">
                            <Input
                                id="b-languages"
                                value={profile.languages.join(", ")}
                                onChange={(e) => set("languages", e.target.value.split(","))}
                                placeholder="français, anglais, dioula"
                            />
                        </Field>
                    </div>
                </TabsContent>

                <TabsContent value="hours" className="grid gap-6 rounded-xl border border-border/60 p-5 lg:grid-cols-[1fr_360px]">
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-end justify-between gap-3">
                            <h3 className="flex items-center gap-2 font-semibold">
                                <Clock className="size-4" /> Horaires d&apos;ouverture
                            </h3>
                            <div className="w-64 space-y-1">
                                <Label>Fuseau horaire</Label>
                                <Select value={profile.timezone} onValueChange={(v) => set("timezone", v)}>
                                    <SelectTrigger aria-label="Fuseau horaire" className="w-full">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {[...new Set([profile.timezone, ...TIMEZONES])].map((tz) => (
                                            <SelectItem key={tz} value={tz}>
                                                {tz}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        <HoursEditor hours={profile.opening_hours} onChange={(v) => set("opening_hours", v)} />
                        <h3 className="pt-2 font-semibold">Fermetures exceptionnelles</h3>
                        <ClosuresEditor closures={profile.closures} onChange={(v) => set("closures", v)} />
                    </div>
                    <div className="space-y-4">
                        <h3 className="font-semibold">Où vous trouver</h3>
                        <Field id="b-address" label="Adresse">
                            <Input {...text("address")} />
                        </Field>
                        <Field id="b-city" label="Ville">
                            <Input {...text("city")} />
                        </Field>
                        <Field id="b-country" label="Pays">
                            <Input {...text("country")} />
                        </Field>
                        <Field id="b-directions" label="Repères et accès" hint="Ce qu'on dirait à quelqu'un au téléphone.">
                            <Textarea {...text("directions")} rows={3} placeholder="En face de la pharmacie, portail bleu" />
                        </Field>
                        <Field id="b-maps_url" label="Lien Google Maps">
                            <Input {...text("maps_url")} placeholder="https://maps.app.goo.gl/…" />
                        </Field>
                    </div>
                </TabsContent>

                <TabsContent value="content" className="grid gap-6 lg:grid-cols-2">
                    <section className="space-y-3 rounded-xl border border-border/60 p-5">
                        <h3 className="font-semibold">Offres et tarifs ({profile.offers.length})</h3>
                        <OffersEditor offers={profile.offers} onChange={(v) => set("offers", v)} />
                    </section>
                    <div className="space-y-6">
                        <section className="space-y-3 rounded-xl border border-border/60 p-5">
                            <h3 className="font-semibold">Questions fréquentes ({profile.faq.length})</h3>
                            <FaqEditor faq={profile.faq} onChange={(v) => set("faq", v)} />
                        </section>
                        <section className="space-y-3 rounded-xl border border-border/60 p-5">
                            <h3 className="font-semibold">Conditions (paiement, livraison, annulation…)</h3>
                            <PoliciesEditor policies={profile.policies} onChange={(v) => set("policies", v)} />
                        </section>
                    </div>
                </TabsContent>

                <TabsContent value="skills" className="space-y-4 rounded-xl border border-border/60 p-5">
                    <p className="text-sm text-muted-foreground">
                        Les compétences communes s&apos;appliquent à tous vos agents, quel que soit le canal.
                    </p>
                    <div className="grid gap-3 md:grid-cols-2">
                        {(Object.keys(SKILL_DESCRIPTIONS) as (keyof Skills)[]).map((skill) => (
                            <label
                                key={skill}
                                className="flex cursor-pointer items-start gap-3 rounded-lg border border-border/60 p-3"
                            >
                                <Switch
                                    checked={profile.skills[skill]}
                                    onCheckedChange={(v) => set("skills", { ...profile.skills, [skill]: v })}
                                    aria-label={skillLabels[skill] ?? skill}
                                />
                                <span>
                                    <span className="block text-sm font-medium">{skillLabels[skill] ?? skill}</span>
                                    <span className="text-xs text-muted-foreground">{SKILL_DESCRIPTIONS[skill]}</span>
                                </span>
                            </label>
                        ))}
                    </div>
                    <Field id="b-instructions" label="Consignes propres à l'entreprise">
                        <Textarea
                            {...text("instructions")}
                            rows={3}
                            placeholder="Ex. : ne jamais promettre de remise ; toujours proposer la livraison."
                        />
                    </Field>
                </TabsContent>

                <TabsContent value="preview" className="space-y-3 rounded-xl border border-border/60 p-5">
                    <div className="flex flex-wrap items-center gap-2">
                        {preview?.opening_status && <Badge variant="secondary">{preview.opening_status}</Badge>}
                        {preview && <span className="text-xs text-muted-foreground">{preview.characters} caractères</span>}
                        {dirty && <span className="text-xs text-amber-400">Aperçu des modifications non enregistrées</span>}
                    </div>
                    {preview?.prompt ? (
                        <pre
                            data-testid="business-preview"
                            className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md border border-border/60 bg-muted/40 p-4 text-sm"
                        >
                            {preview.prompt}
                        </pre>
                    ) : (
                        <p className="text-sm text-muted-foreground">
                            {profile.enabled
                                ? "Renseignez au moins le nom de l'entreprise pour que vos agents reçoivent la fiche."
                                : "La fiche n'est pas donnée aux agents (interrupteur « Donnée aux agents »)."}
                        </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                        Ce texte est ajouté au prompt de chaque agent. Un agent peut s&apos;en passer (réglages de
                        l&apos;agent) ou le placer lui-même avec <code>{"{{business_profile}}"}</code>, et utiliser
                        <code>{" {{business.name}}"}</code>, <code>{"{{business.phone}}"}</code>… dans ses messages.
                    </p>
                </TabsContent>
            </Tabs>

            <TemplateDialog
                template={openTemplate}
                isCurrent={openTemplate?.id === profile.industry}
                onClose={() => setOpenTemplate(null)}
                onApply={applyTemplate}
                onCreateAgent={createAgent}
                skillLabels={skillLabels}
            />
        </PageLayout>
    );
}

"use client";

import { Building2, Link2, Plus, Tags } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createCompanyApiV1ResellerCompaniesPost,
    createOfferApiV1ResellerPlansPost,
    getResellerApiV1ResellerGet,
    inviteToCompanyApiV1ResellerCompaniesOrganizationIdInvitationsPost,
    listBasePlansApiV1ResellerBasePlansGet,
    listCompaniesApiV1ResellerCompaniesGet,
    listOffersApiV1ResellerPlansGet,
    updateCompanyApiV1ResellerCompaniesOrganizationIdPatch,
    updateOfferApiV1ResellerPlansCodePut,
} from "@/client/sdk.gen";
import type { Company, ResellerInfo, ResellerPlan } from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { InvitationLinkDialog } from "@/components/saas/InvitationLinkDialog";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { formatLimit, formatPrice, STATUS_LABELS } from "@/lib/enterpriseApi";
import { resumedStatus } from "@/lib/resellers";

const LIMITS = [
    { key: "included_minutes", label: "Minutes IA / mois" },
    { key: "included_human_minutes", label: "Minutes humaines / mois" },
    { key: "max_concurrent_calls", label: "Appels simultanés" },
    { key: "max_agents", label: "Agents IA" },
    { key: "max_human_seats", label: "Postes humains" },
    { key: "max_campaigns", label: "Campagnes" },
] as const;
type LimitKey = (typeof LIMITS)[number]["key"];

const FEATURE_LABELS: Record<string, string> = {
    local_ai: "IA locale",
    contact_center: "Centre d'appels",
    campaigns: "Campagnes",
    api_access: "Accès API",
    white_label: "Marque blanche",
    custom_voices: "Voix personnalisées",
    pbx_shared: "PBX partagé",
    pbx_dedicated: "PBX dédié",
};

const statusLabel = (status: string | null | undefined) =>
    status ? (STATUS_LABELS as Record<string, string>)[status] ?? status : "—";

// ------------------------------------------------------------------- offers

interface OfferDraft {
    code: string | null;
    base_plan_code: string;
    name: string;
    description: string;
    price: string;
    limits: Partial<Record<LimitKey, number | null>>;
    features: Record<string, boolean>;
}

function OfferDialog({
    draft,
    bases,
    onClose,
    onSaved,
}: {
    draft: OfferDraft | null;
    bases: ResellerPlan[];
    onClose: () => void;
    onSaved: () => void;
}) {
    const [offer, setOffer] = useState<OfferDraft | null>(draft);
    const [saving, setSaving] = useState(false);
    useEffect(() => setOffer(draft), [draft]);
    const base = bases.find((b) => b.code === offer?.base_plan_code);

    const pickBase = (code: string) => {
        const next = bases.find((b) => b.code === code);
        if (!next || !offer) return;
        setOffer({
            ...offer,
            base_plan_code: code,
            price: offer.price || String(next.monthly_price_cents / 100),
            limits: Object.fromEntries(LIMITS.map(({ key }) => [key, next[key] ?? null])),
            features: Object.fromEntries(Object.entries(next.features).filter(([, on]) => on)),
        });
    };

    async function save() {
        if (!offer || !base) return;
        setSaving(true);
        const body = {
            base_plan_code: offer.base_plan_code,
            name: offer.name.trim(),
            description: offer.description.trim() || null,
            monthly_price_cents: Math.round(Number(offer.price.replace(",", ".")) * 100),
            limits: offer.limits,
            features: offer.features,
        };
        const response = offer.code
            ? await updateOfferApiV1ResellerPlansCodePut({ path: { code: offer.code }, body })
            : await createOfferApiV1ResellerPlansPost({ body });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Offre non enregistrée"));
            return;
        }
        toast.success("Offre enregistrée");
        onSaved();
    }

    return (
        <Dialog open={offer !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle>{offer?.code ? "Modifier l'offre" : "Nouvelle offre"}</DialogTitle>
                    <DialogDescription>
                        Construite sur une offre de la plateforme : vos limites ne dépassent pas les siennes et votre
                        prix ne descend pas sous le sien.
                    </DialogDescription>
                </DialogHeader>
                {offer && (
                    <div className="grid gap-3">
                        <div className="grid gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                                <Label>Offre de base</Label>
                                <Select value={offer.base_plan_code} onValueChange={pickBase}>
                                    <SelectTrigger aria-label="Offre de base" className="w-full">
                                        <SelectValue placeholder="Choisir" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {bases.map((b) => (
                                            <SelectItem key={b.code} value={b.code}>
                                                {b.name} · dès {formatPrice(b.monthly_price_cents, b.currency)}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="offer-price">Prix mensuel ({base?.currency.toUpperCase() ?? "EUR"})</Label>
                                <Input
                                    id="offer-price"
                                    inputMode="decimal"
                                    value={offer.price}
                                    onChange={(e) => setOffer({ ...offer, price: e.target.value })}
                                />
                                {base && (
                                    <p className="text-xs text-muted-foreground">
                                        Au moins {formatPrice(base.monthly_price_cents, base.currency)}
                                    </p>
                                )}
                            </div>
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="offer-name">Nom</Label>
                            <Input id="offer-name" value={offer.name} onChange={(e) => setOffer({ ...offer, name: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="offer-description">Description</Label>
                            <Textarea
                                id="offer-description"
                                value={offer.description}
                                onChange={(e) => setOffer({ ...offer, description: e.target.value })}
                            />
                        </div>
                        {base && (
                            <>
                                <div className="grid gap-3 sm:grid-cols-3">
                                    {LIMITS.map(({ key, label }) => (
                                        <div key={key} className="space-y-1">
                                            <Label htmlFor={`limit-${key}`}>{label}</Label>
                                            <Input
                                                id={`limit-${key}`}
                                                type="number"
                                                min={0}
                                                max={base[key] ?? undefined}
                                                placeholder={base[key] == null ? "Illimité" : undefined}
                                                value={offer.limits[key] ?? ""}
                                                onChange={(e) =>
                                                    setOffer({
                                                        ...offer,
                                                        limits: {
                                                            ...offer.limits,
                                                            [key]: e.target.value === "" ? null : Number(e.target.value),
                                                        },
                                                    })
                                                }
                                            />
                                            <p className="text-xs text-muted-foreground">Au plus {formatLimit(base[key])}</p>
                                        </div>
                                    ))}
                                </div>
                                <div className="flex flex-wrap gap-4">
                                    {Object.entries(base.features)
                                        .filter(([, on]) => on)
                                        .map(([feature]) => (
                                            <label key={feature} className="flex items-center gap-2 text-sm">
                                                <Checkbox
                                                    checked={Boolean(offer.features[feature])}
                                                    onCheckedChange={(checked) =>
                                                        setOffer({ ...offer, features: { ...offer.features, [feature]: checked === true } })
                                                    }
                                                />
                                                {FEATURE_LABELS[feature] ?? feature}
                                            </label>
                                        ))}
                                </div>
                            </>
                        )}
                    </div>
                )}
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button type="button" onClick={() => void save()} disabled={saving || !base || !offer?.name.trim()}>
                        Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

// ---------------------------------------------------------------- companies

function CompanyDialog({
    open,
    offers,
    onClose,
    onCreated,
}: {
    open: boolean;
    offers: ResellerPlan[];
    onClose: () => void;
    onCreated: (url: string) => void;
}) {
    const [form, setForm] = useState({ company_name: "", owner_email: "", owner_name: "", plan_code: "" });
    const [saving, setSaving] = useState(false);

    async function create() {
        setSaving(true);
        const response = await createCompanyApiV1ResellerCompaniesPost({
            body: { ...form, owner_name: form.owner_name || null },
        });
        setSaving(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Entreprise non créée"));
            return;
        }
        setForm({ company_name: "", owner_email: "", owner_name: "", plan_code: "" });
        onCreated(response.data.invitation_url);
    }

    return (
        <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Nouvelle entreprise cliente</DialogTitle>
                    <DialogDescription>
                        Elle démarre en essai sur l&apos;offre choisie ; son responsable reçoit un lien pour créer son
                        compte.
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-3">
                    <div className="space-y-1">
                        <Label htmlFor="company-name">Entreprise</Label>
                        <Input id="company-name" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1">
                            <Label htmlFor="owner-email">E-mail du responsable</Label>
                            <Input id="owner-email" type="email" value={form.owner_email} onChange={(e) => setForm({ ...form, owner_email: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="owner-name">Nom (facultatif)</Label>
                            <Input id="owner-name" value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} />
                        </div>
                    </div>
                    <div className="space-y-1">
                        <Label>Offre</Label>
                        <Select value={form.plan_code} onValueChange={(plan_code) => setForm({ ...form, plan_code })}>
                            <SelectTrigger aria-label="Offre" className="w-full">
                                <SelectValue placeholder={offers.length ? "Choisir une offre" : "Créez d'abord une offre"} />
                            </SelectTrigger>
                            <SelectContent>
                                {offers.map((o) => (
                                    <SelectItem key={o.code} value={o.code}>
                                        {o.name} · {formatPrice(o.monthly_price_cents, o.currency)}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <DialogFooter>
                    <Button type="button" variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button
                        type="button"
                        onClick={() => void create()}
                        disabled={saving || !form.company_name.trim() || !form.owner_email.trim() || !form.plan_code}
                    >
                        Créer et obtenir le lien
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

// --------------------------------------------------------------------- page

export default function ResellerPage() {
    const { user, loading: authLoading } = useAuth();
    const hasFetched = useRef(false);
    const [info, setInfo] = useState<ResellerInfo | null>(null);
    const [denied, setDenied] = useState<string | null>(null);
    const [companies, setCompanies] = useState<Company[]>([]);
    const [offers, setOffers] = useState<ResellerPlan[]>([]);
    const [bases, setBases] = useState<ResellerPlan[]>([]);
    const [offerDraft, setOfferDraft] = useState<OfferDraft | null>(null);
    const [newCompany, setNewCompany] = useState(false);
    const [link, setLink] = useState<string | null>(null);

    const load = useCallback(async () => {
        const me = await getResellerApiV1ResellerGet();
        if (me.error || !me.data) {
            setDenied(detailFromError(me.error, "Console réservée aux revendeurs"));
            return;
        }
        setInfo(me.data);
        const [c, o, b] = await Promise.all([
            listCompaniesApiV1ResellerCompaniesGet(),
            listOffersApiV1ResellerPlansGet(),
            listBasePlansApiV1ResellerBasePlansGet(),
        ]);
        setCompanies(c.data ?? []);
        setOffers(o.data ?? []);
        setBases(b.data ?? []);
    }, []);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void load();
    }, [authLoading, user, load]);

    const offerName = useMemo(() => new Map(offers.map((o) => [o.code, o.name])), [offers]);

    async function updateCompany(organizationId: number, body: { plan_code?: string; status?: "trialing" | "active" | "suspended" }) {
        const response = await updateCompanyApiV1ResellerCompaniesOrganizationIdPatch({ path: { organization_id: organizationId }, body });
        if (response.error) {
            toast.error(detailFromError(response.error, "Modification impossible"));
            return;
        }
        toast.success("Entreprise mise à jour");
        void load();
    }

    async function newLink(company: Company) {
        if (!company.billing_email) return;
        const response = await inviteToCompanyApiV1ResellerCompaniesOrganizationIdInvitationsPost({
            path: { organization_id: company.organization_id },
            body: { email: company.billing_email },
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Lien non créé"));
            return;
        }
        setLink(response.data.invitation_url);
    }

    if (denied) {
        return (
            <PageLayout title="Console revendeur">
                <p className="text-sm text-muted-foreground">{denied}</p>
            </PageLayout>
        );
    }

    return (
        <PageLayout
            title={info ? `Console revendeur · ${info.name}` : "Console revendeur"}
            description={
                info
                    ? `${info.companies} entreprise${info.companies > 1 ? "s" : ""} cliente${info.companies > 1 ? "s" : ""} · commission de la plateforme : ${info.commission_percent.toLocaleString("fr-FR")} % · paiement en ligne : ${info.stripe_ready ? "actif" : "à connecter"}`
                    : undefined
            }
        >
            <Tabs defaultValue="companies">
                <TabsList>
                    <TabsTrigger value="companies">
                        <Building2 /> Entreprises
                    </TabsTrigger>
                    <TabsTrigger value="offers">
                        <Tags /> Offres
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="companies">
                    <PageSection
                        title="Entreprises clientes"
                        description="Vos clients : leur offre, leur statut, un nouveau lien d'accès si besoin."
                        actions={
                            <Button type="button" onClick={() => setNewCompany(true)} disabled={offers.length === 0}>
                                <Plus /> Nouvelle entreprise
                            </Button>
                        }
                    >
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Entreprise</TableHead>
                                    <TableHead>Responsable</TableHead>
                                    <TableHead>Offre</TableHead>
                                    <TableHead>Statut</TableHead>
                                    <TableHead className="text-right">Actions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {companies.length === 0 && (
                                    <TableRow>
                                        <TableCell colSpan={5} className="text-center text-muted-foreground">
                                            {offers.length ? "Aucune entreprise pour l'instant." : "Créez d'abord une offre, puis vos entreprises."}
                                        </TableCell>
                                    </TableRow>
                                )}
                                {companies.map((company) => (
                                    <TableRow key={company.organization_id}>
                                        <TableCell className="font-medium">{company.company_name ?? `#${company.organization_id}`}</TableCell>
                                        <TableCell>{company.billing_email ?? "—"}</TableCell>
                                        <TableCell>
                                            <Select
                                                value={company.plan_code ?? undefined}
                                                onValueChange={(plan_code) => void updateCompany(company.organization_id, { plan_code })}
                                            >
                                                <SelectTrigger aria-label={`Offre de ${company.company_name ?? ""}`} className="w-48">
                                                    <SelectValue>{company.plan_code ? offerName.get(company.plan_code) ?? company.plan_name : "—"}</SelectValue>
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {offers.map((o) => (
                                                        <SelectItem key={o.code} value={o.code}>
                                                            {o.name}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </TableCell>
                                        <TableCell>
                                            <Badge variant={company.status === "suspended" ? "destructive" : "secondary"}>{statusLabel(company.status)}</Badge>
                                        </TableCell>
                                        <TableCell className="space-x-1 text-right">
                                            <Button type="button" variant="ghost" size="sm" onClick={() => void newLink(company)}>
                                                <Link2 /> Lien d&apos;accès
                                            </Button>
                                            {company.status === "suspended" ? (
                                                <Button type="button" variant="outline" size="sm" onClick={() => void updateCompany(company.organization_id, { status: resumedStatus(company) })}>
                                                    Réactiver
                                                </Button>
                                            ) : (
                                                <Button type="button" variant="outline" size="sm" onClick={() => void updateCompany(company.organization_id, { status: "suspended" })}>
                                                    Suspendre
                                                </Button>
                                            )}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </PageSection>
                </TabsContent>

                <TabsContent value="offers">
                    <PageSection
                        title="Vos offres"
                        description="Votre nom, votre prix, sur la base d'une offre de la plateforme."
                        actions={
                            <Button
                                type="button"
                                onClick={() =>
                                    setOfferDraft({ code: null, base_plan_code: "", name: "", description: "", price: "", limits: {}, features: {} })
                                }
                            >
                                <Plus /> Nouvelle offre
                            </Button>
                        }
                    >
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Offre</TableHead>
                                    <TableHead>Prix / mois</TableHead>
                                    <TableHead>Base</TableHead>
                                    <TableHead>Minutes IA</TableHead>
                                    <TableHead>Postes humains</TableHead>
                                    <TableHead />
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {offers.length === 0 && (
                                    <TableRow>
                                        <TableCell colSpan={6} className="text-center text-muted-foreground">
                                            Aucune offre pour l&apos;instant.
                                        </TableCell>
                                    </TableRow>
                                )}
                                {offers.map((offer) => (
                                    <TableRow key={offer.code}>
                                        <TableCell className="font-medium">{offer.name}</TableCell>
                                        <TableCell>{formatPrice(offer.monthly_price_cents, offer.currency)}</TableCell>
                                        <TableCell>{bases.find((b) => b.code === offer.base_plan_code)?.name ?? offer.base_plan_code}</TableCell>
                                        <TableCell>{formatLimit(offer.included_minutes)}</TableCell>
                                        <TableCell>{formatLimit(offer.max_human_seats)}</TableCell>
                                        <TableCell className="text-right">
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                onClick={() =>
                                                    setOfferDraft({
                                                        code: offer.code,
                                                        base_plan_code: offer.base_plan_code ?? "",
                                                        name: offer.name,
                                                        description: offer.description ?? "",
                                                        price: String(offer.monthly_price_cents / 100),
                                                        limits: Object.fromEntries(LIMITS.map(({ key }) => [key, offer[key] ?? null])),
                                                        features: offer.features,
                                                    })
                                                }
                                            >
                                                Modifier
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </PageSection>
                </TabsContent>
            </Tabs>

            <OfferDialog
                draft={offerDraft}
                bases={bases}
                onClose={() => setOfferDraft(null)}
                onSaved={() => {
                    setOfferDraft(null);
                    void load();
                }}
            />
            <CompanyDialog
                open={newCompany}
                offers={offers}
                onClose={() => setNewCompany(false)}
                onCreated={(url) => {
                    setNewCompany(false);
                    setLink(url);
                    void load();
                }}
            />
            <InvitationLinkDialog url={link} title="Lien d'accès de l'entreprise" onClose={() => setLink(null)} />
        </PageLayout>
    );
}

"use client";

import { Building2, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/auth";
import {
    ApiError,
    enterpriseApi,
    formatLimit,
    formatPrice,
    type Plan,
    STATUS_LABELS,
    type Subscription,
    type Tenant,
} from "@/lib/enterpriseApi";

const STATUSES = Object.keys(STATUS_LABELS) as Subscription["status"][];

const LIMIT_FIELDS: { key: string; label: string }[] = [
    { key: "included_minutes", label: "Minutes incluses / mois" },
    { key: "max_concurrent_calls", label: "Appels simultanés" },
    { key: "max_agents", label: "Agents IA" },
    { key: "max_human_seats", label: "Postes humains" },
    { key: "max_campaigns", label: "Campagnes" },
];

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");

function TenantDialog({
    tenant,
    plans,
    onClose,
    onSaved,
}: {
    tenant: Tenant | null;
    plans: Plan[];
    onClose: () => void;
    onSaved: () => void;
}) {
    const [plan, setPlan] = useState("");
    const [status, setStatus] = useState<Subscription["status"]>("active");
    const [company, setCompany] = useState("");
    const [email, setEmail] = useState("");
    const [notes, setNotes] = useState("");
    const [overrides, setOverrides] = useState<Record<string, string>>({});
    const [usage, setUsage] = useState<Subscription | null>(null);

    useEffect(() => {
        if (!tenant) return;
        setPlan(tenant.plan_code);
        setStatus(tenant.status);
        setCompany(tenant.company_name ?? "");
        setEmail(tenant.billing_email ?? "");
        setNotes(tenant.notes ?? "");
        const o: Record<string, string> = {};
        for (const f of LIMIT_FIELDS) {
            const v = tenant.limit_overrides?.[f.key];
            o[f.key] = v === undefined ? "" : v === null ? "illimité" : String(v);
        }
        setOverrides(o);
        setUsage(null);
        enterpriseApi.adminTenantUsage(tenant.organization_id).then(setUsage).catch(() => undefined);
    }, [tenant]);

    const save = async () => {
        if (!tenant) return;
        const limit_overrides: Record<string, number | null> = {};
        for (const [key, raw] of Object.entries(overrides)) {
            const value = raw.trim().toLowerCase();
            if (!value) continue;
            if (value === "illimité" || value === "illimite") limit_overrides[key] = null;
            else if (/^\d+$/.test(value)) limit_overrides[key] = Number(value);
            else {
                toast.error(`Valeur invalide pour ${key}`);
                return;
            }
        }
        try {
            await enterpriseApi.adminUpdateTenant(tenant.organization_id, {
                plan_code: plan !== tenant.plan_code ? plan : undefined,
                status,
                company_name: company,
                ...(email ? { billing_email: email } : {}),
                notes,
                limit_overrides,
            });
            toast.success("Client mis à jour");
            onSaved();
            onClose();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Mise à jour impossible");
        }
    };

    return (
        <Dialog open={tenant !== null} onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle>Client #{tenant?.organization_id}</DialogTitle>
                    <DialogDescription>{tenant?.member_emails.join(", ")}</DialogDescription>
                </DialogHeader>
                {usage && (
                    <p className="text-sm text-muted-foreground">
                        Consommation de la période : {usage.used_minutes.toLocaleString("fr-FR")} min sur{" "}
                        {formatLimit(usage.included_minutes)}
                        {usage.blocked_reason ? ` — bloqué (${usage.blocked_reason})` : ""}
                    </p>
                )}
                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                        <Label>Offre</Label>
                        <Select value={plan} onValueChange={setPlan}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {plans.map((p) => (
                                    <SelectItem key={p.code} value={p.code}>
                                        {p.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-1">
                        <Label>Statut</Label>
                        <Select value={status} onValueChange={(v) => setStatus(v as Subscription["status"])}>
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {STATUSES.map((s) => (
                                    <SelectItem key={s} value={s}>
                                        {STATUS_LABELS[s]}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-1">
                        <Label>Société</Label>
                        <Input value={company} onChange={(e) => setCompany(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label>E-mail de facturation</Label>
                        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                    </div>
                </div>
                <div className="space-y-2">
                    <Label>Limites spécifiques à ce client (vide = celles de l&apos;offre, « illimité » accepté)</Label>
                    <div className="grid grid-cols-3 gap-3">
                        {LIMIT_FIELDS.map((f) => (
                            <div key={f.key} className="space-y-1">
                                <span className="text-xs text-muted-foreground">{f.label}</span>
                                <Input
                                    value={overrides[f.key] ?? ""}
                                    onChange={(e) => setOverrides((o) => ({ ...o, [f.key]: e.target.value }))}
                                />
                            </div>
                        ))}
                    </div>
                </div>
                <div className="space-y-1">
                    <Label>Notes internes</Label>
                    <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button onClick={save}>Enregistrer</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function PlanEditor({ plan, onSaved }: { plan: Plan; onSaved: () => void }) {
    const [price, setPrice] = useState(String(plan.monthly_price_cents / 100));
    const [minutes, setMinutes] = useState(plan.included_minutes === null ? "" : String(plan.included_minutes));
    const [stripePrice, setStripePrice] = useState("");
    const save = async () => {
        try {
            await enterpriseApi.adminUpsertPlan(plan.code, {
                monthly_price_cents: Math.round(Number(price) * 100),
                ...(minutes === "" ? { unlimited: ["included_minutes"] } : { included_minutes: Number(minutes) }),
                ...(stripePrice ? { stripe_price_id: stripePrice } : {}),
            } as Partial<Plan> & { unlimited?: string[]; stripe_price_id?: string });
            toast.success(`Offre ${plan.name} enregistrée`);
            onSaved();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Enregistrement impossible");
        }
    };
    return (
        <TableRow>
            <TableCell className="font-medium">
                {plan.name} <code className="text-xs text-muted-foreground">{plan.code}</code>
            </TableCell>
            <TableCell>
                <Input className="w-24" value={price} onChange={(e) => setPrice(e.target.value)} />
            </TableCell>
            <TableCell>
                <Input className="w-24" placeholder="illimité" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
            </TableCell>
            <TableCell>
                <Input
                    className="w-48"
                    placeholder={plan.purchasable ? "configuré" : "price_…"}
                    value={stripePrice}
                    onChange={(e) => setStripePrice(e.target.value)}
                />
            </TableCell>
            <TableCell className="text-right">
                <Button size="sm" variant="outline" onClick={save}>
                    <Save className="mr-1 h-4 w-4" />
                    Enregistrer
                </Button>
            </TableCell>
        </TableRow>
    );
}

export default function TenantsPage() {
    const { user, loading } = useAuth();
    const [tenants, setTenants] = useState<Tenant[] | null>(null);
    const [total, setTotal] = useState(0);
    const [plans, setPlans] = useState<Plan[]>([]);
    const [filter, setFilter] = useState<string>("all");
    const [selected, setSelected] = useState<Tenant | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [list, planList] = await Promise.all([
                enterpriseApi.adminListTenants(1, filter === "all" ? undefined : filter),
                enterpriseApi.adminListPlans(),
            ]);
            setTenants(list.tenants);
            setTotal(list.total);
            setPlans(planList);
        } catch (e) {
            setError(
                e instanceof ApiError && (e.status === 403 || e.status === 401)
                    ? "Réservé à l'opérateur de la plateforme (super-admin)."
                    : e instanceof ApiError && e.status === 404
                      ? "Le mode SaaS multi-entreprises n'est pas activé (SAAS_MODE)."
                      : "Chargement impossible.",
            );
        }
    }, [filter]);

    useEffect(() => {
        if (!loading && user) void load();
    }, [loading, user, load]);

    if (error) {
        return (
            <PageLayout title="Clients et abonnements">
                <Card>
                    <CardContent className="pt-6 text-muted-foreground">{error}</CardContent>
                </Card>
            </PageLayout>
        );
    }

    return (
        <PageLayout
            title="Clients et abonnements"
            description="Console opérateur : entreprises abonnées, offres, quotas et statuts."
        >
            <PageSection
                title={
                    <span className="flex items-center gap-2">
                        <Building2 className="h-5 w-5" /> Entreprises clientes ({total})
                    </span>
                }
                actions={
                    <Select value={filter} onValueChange={setFilter}>
                        <SelectTrigger className="w-48">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">Tous les statuts</SelectItem>
                            {STATUSES.map((s) => (
                                <SelectItem key={s} value={s}>
                                    {STATUS_LABELS[s]}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                }
            >
                {tenants === null ? (
                    <Skeleton className="h-40 w-full" />
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>#</TableHead>
                                <TableHead>Société / contacts</TableHead>
                                <TableHead>Offre</TableHead>
                                <TableHead>Statut</TableHead>
                                <TableHead>Fin de période</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {tenants.map((t) => (
                                <TableRow key={t.organization_id}>
                                    <TableCell>{t.organization_id}</TableCell>
                                    <TableCell>
                                        <div className="font-medium">{t.company_name || "—"}</div>
                                        <div className="text-xs text-muted-foreground">
                                            {t.member_emails.slice(0, 2).join(", ")}
                                        </div>
                                    </TableCell>
                                    <TableCell>{plans.find((p) => p.code === t.plan_code)?.name ?? t.plan_code}</TableCell>
                                    <TableCell>
                                        <Badge variant={t.status === "active" ? "default" : "secondary"}>
                                            {STATUS_LABELS[t.status]}
                                        </Badge>
                                    </TableCell>
                                    <TableCell>
                                        {t.status === "trialing" ? fmtDate(t.trial_ends_at) : fmtDate(t.current_period_end)}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button size="sm" variant="outline" onClick={() => setSelected(t)}>
                                            Gérer
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <PageSection
                title="Offres"
                description="Prix mensuel HT en euros. Renseignez l'identifiant de prix Stripe pour activer le paiement en ligne."
            >
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Offre</TableHead>
                            <TableHead>Prix (€)</TableHead>
                            <TableHead>Minutes</TableHead>
                            <TableHead>Prix Stripe</TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {plans.map((plan) => (
                            <PlanEditor key={plan.code} plan={plan} onSaved={load} />
                        ))}
                    </TableBody>
                </Table>
                <p className="text-xs text-muted-foreground">
                    Tarifs affichés aux clients :{" "}
                    {plans.map((p) => `${p.name} ${formatPrice(p.monthly_price_cents, p.currency)}`).join(" · ")}
                </p>
            </PageSection>

            <TenantDialog tenant={selected} plans={plans} onClose={() => setSelected(null)} onSaved={load} />
        </PageLayout>
    );
}

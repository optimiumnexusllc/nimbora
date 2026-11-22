"use client";

import { AlertTriangle, Check, CreditCard, ExternalLink, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { HumanMinutes } from "@/components/subscription/HumanMinutes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import {
    BLOCKED_REASON_LABELS,
    enterpriseApi,
    FEATURE_LABELS,
    formatLimit,
    formatPrice,
    type Plan,
    STATUS_LABELS,
    type Subscription,
} from "@/lib/enterpriseApi";

const LIMIT_ROWS: { key: string; label: string }[] = [
    { key: "max_concurrent_calls", label: "Appels simultanés" },
    { key: "max_agents", label: "Agents IA" },
    { key: "max_human_seats", label: "Postes d'agents humains" },
    { key: "max_campaigns", label: "Campagnes" },
];

const formatDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "—";

function SubscriptionContent() {
    const { user, loading } = useAuth();
    const searchParams = useSearchParams();
    const [subscription, setSubscription] = useState<Subscription | null>(null);
    const [plans, setPlans] = useState<Plan[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [busyPlan, setBusyPlan] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [sub, planList] = await Promise.all([
                enterpriseApi.getSubscription(),
                enterpriseApi.listPlans(),
            ]);
            setSubscription(sub);
            setPlans(planList);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Impossible de charger l'abonnement.");
        }
    }, []);

    useEffect(() => {
        if (!loading && user) void load();
    }, [loading, user, load]);

    useEffect(() => {
        const checkout = searchParams.get("checkout");
        if (checkout === "success") toast.success("Paiement confirmé — votre offre est active.");
        if (checkout === "cancel") toast.info("Paiement annulé.");
    }, [searchParams]);

    const choosePlan = async (plan: Plan) => {
        setBusyPlan(plan.code);
        try {
            const { url } = await enterpriseApi.startCheckout(plan.code);
            window.location.assign(url);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Paiement indisponible.");
            setBusyPlan(null);
        }
    };

    const openPortal = async () => {
        try {
            const { url } = await enterpriseApi.openBillingPortal();
            window.location.assign(url);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Portail de paiement indisponible.");
        }
    };

    if (error) {
        return (
            <PageLayout title="Abonnement">
                <Card>
                    <CardContent className="pt-6 text-muted-foreground">{error}</CardContent>
                </Card>
            </PageLayout>
        );
    }

    if (!subscription) {
        return (
            <PageLayout title="Abonnement">
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-64 w-full" />
            </PageLayout>
        );
    }

    const usedPct =
        subscription.included_minutes && subscription.included_minutes > 0
            ? Math.min(100, (subscription.used_minutes / subscription.included_minutes) * 100)
            : 0;

    return (
        <PageLayout
            title="Abonnement"
            description={`Votre offre ${subscription.platform_name}, votre consommation et vos limites.`}
            actions={
                subscription.can_manage_billing ? (
                    <Button variant="outline" onClick={openPortal}>
                        <CreditCard className="mr-2 h-4 w-4" />
                        Moyens de paiement et factures
                        <ExternalLink className="ml-2 h-3 w-3" />
                    </Button>
                ) : null
            }
        >
            {!subscription.usable && subscription.blocked_reason && (
                <Card className="border-destructive">
                    <CardContent className="flex items-start gap-3 pt-6">
                        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                        <p>
                            {BLOCKED_REASON_LABELS[subscription.blocked_reason] ??
                                "Les appels sont actuellement bloqués sur votre compte."}
                        </p>
                    </CardContent>
                </Card>
            )}

            <PageSection
                title={
                    <span className="flex items-center gap-3">
                        Offre {subscription.plan_name}
                        <Badge variant={subscription.status === "active" ? "default" : "secondary"}>
                            {STATUS_LABELS[subscription.status]}
                        </Badge>
                    </span>
                }
                description={
                    subscription.status === "trialing"
                        ? `Essai gratuit jusqu'au ${formatDate(subscription.trial_ends_at)}`
                        : `Période en cours : du ${formatDate(subscription.period_start)} au ${formatDate(subscription.period_end)}`
                }
            >
                <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                        <span>Minutes des agents IA</span>
                        <span className="font-medium">
                            {subscription.used_minutes.toLocaleString("fr-FR")} / {formatLimit(subscription.included_minutes)}
                        </span>
                    </div>
                    {subscription.included_minutes !== null && <Progress value={usedPct} />}
                    {subscription.overage_minutes > 0 && (
                        <p className="text-sm text-muted-foreground">
                            Dépassement : {subscription.overage_minutes.toLocaleString("fr-FR")} min (≈{" "}
                            {formatPrice(subscription.estimated_overage_cents, "eur")})
                        </p>
                    )}
                </div>
                <HumanMinutes subscription={subscription} />
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                    {LIMIT_ROWS.map((row) => (
                        <div key={row.key} className="rounded-md border p-3">
                            <div className="text-xs text-muted-foreground">{row.label}</div>
                            <div className="text-lg font-semibold">{formatLimit(subscription.limits[row.key])}</div>
                        </div>
                    ))}
                </div>
            </PageSection>

            <div>
                <h2 className="mb-4 text-xl font-semibold">Offres disponibles</h2>
                <div className="grid gap-4 md:grid-cols-3">
                    {plans.map((plan) => {
                        const current = plan.code === subscription.plan_code;
                        return (
                            <Card key={plan.code} className={current ? "border-primary" : undefined}>
                                <CardHeader>
                                    <CardTitle className="flex items-center justify-between">
                                        {plan.name}
                                        {current && <Badge>Offre actuelle</Badge>}
                                    </CardTitle>
                                    <CardDescription>{plan.description}</CardDescription>
                                    <div className="pt-2 text-3xl font-bold">
                                        {formatPrice(plan.monthly_price_cents, plan.currency)}
                                        <span className="text-sm font-normal text-muted-foreground"> / mois HT</span>
                                    </div>
                                </CardHeader>
                                <CardContent className="space-y-2 text-sm">
                                    <div>{formatLimit(plan.included_minutes, " minutes")} incluses</div>
                                    {plan.overage_price_cents_per_minute ? (
                                        <div className="text-muted-foreground">
                                            puis {formatPrice(plan.overage_price_cents_per_minute, plan.currency)} / min
                                        </div>
                                    ) : null}
                                    {plan.included_human_minutes !== undefined && (
                                        <div>
                                            {formatLimit(plan.included_human_minutes, " minutes")} d&apos;appels humains (PBX)
                                            {plan.human_overage_price_cents_per_minute
                                                ? `, puis ${formatPrice(plan.human_overage_price_cents_per_minute, plan.currency)} / min`
                                                : ""}
                                        </div>
                                    )}
                                    <div>{formatLimit(plan.max_concurrent_calls)} appels simultanés</div>
                                    <div>{formatLimit(plan.max_agents)} agents IA</div>
                                    <div>{formatLimit(plan.max_human_seats)} postes humains</div>
                                    <ul className="space-y-1 pt-2">
                                        {Object.entries(plan.features)
                                            .filter(([, enabled]) => enabled)
                                            .map(([feature]) => (
                                                <li key={feature} className="flex items-start gap-2">
                                                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                                                    {FEATURE_LABELS[feature] ?? feature}
                                                </li>
                                            ))}
                                    </ul>
                                </CardContent>
                                <CardFooter>
                                    {current && subscription.status === "active" ? (
                                        <Button className="w-full" variant="outline" disabled>
                                            Offre actuelle
                                        </Button>
                                    ) : plan.purchasable ? (
                                        <Button
                                            className="w-full"
                                            onClick={() => choosePlan(plan)}
                                            disabled={busyPlan !== null}
                                        >
                                            {busyPlan === plan.code && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                            {current ? "Activer cette offre" : "Choisir cette offre"}
                                        </Button>
                                    ) : (
                                        <p className="w-full text-center text-sm text-muted-foreground">
                                            Contactez-nous pour souscrire
                                        </p>
                                    )}
                                </CardFooter>
                            </Card>
                        );
                    })}
                </div>
            </div>
        </PageLayout>
    );
}

export default function SubscriptionPage() {
    return (
        <Suspense fallback={null}>
            <SubscriptionContent />
        </Suspense>
    );
}

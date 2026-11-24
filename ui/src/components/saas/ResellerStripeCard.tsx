"use client";

import { CreditCard, ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getStripeStateApiV1ResellerStripeGet,
    openStripeDashboardApiV1ResellerStripeDashboardPost,
    startStripeOnboardingApiV1ResellerStripeOnboardingPost,
} from "@/client/sdk.gen";
import type { StripeState } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";

/** The reseller's Stripe Express account: its companies' payments land there,
 *  minus the platform's commission. */
export function ResellerStripeCard({ commissionPercent }: { commissionPercent: number }) {
    const [state, setState] = useState<StripeState | null>(null);
    const [busy, setBusy] = useState(false);
    const loaded = useRef(false);

    useEffect(() => {
        if (loaded.current) return;
        loaded.current = true;
        void getStripeStateApiV1ResellerStripeGet().then((response) => {
            if (response.error) {
                toast.error(detailFromError(response.error, "État Stripe indisponible"));
                return;
            }
            setState(response.data ?? null);
        });
        const back = new URLSearchParams(window.location.search).get("stripe");
        if (back === "return") toast.success("Retour de Stripe : l'état de votre compte est à jour.");
    }, []);

    async function open(kind: "onboarding" | "dashboard") {
        setBusy(true);
        const response =
            kind === "onboarding"
                ? await startStripeOnboardingApiV1ResellerStripeOnboardingPost()
                : await openStripeDashboardApiV1ResellerStripeDashboardPost();
        setBusy(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Stripe indisponible"));
            return;
        }
        window.location.assign(response.data.url);
    }

    const ready = state?.charges_enabled;
    return (
        <PageSection
            title="Paiement en ligne"
            description={`Vos clients paient leur abonnement en ligne ; l'argent arrive sur votre compte Stripe, moins la commission de la plateforme (${commissionPercent.toLocaleString("fr-FR")} %).`}
        >
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border/60 p-4" data-testid="reseller-stripe">
                <CreditCard className="size-5 text-muted-foreground" />
                {state === null ? (
                    <span className="text-sm text-muted-foreground">Chargement…</span>
                ) : ready ? (
                    <Badge>Actif</Badge>
                ) : state.connected ? (
                    <Badge variant="outline">Inscription à terminer</Badge>
                ) : (
                    <Badge variant="outline">Non connecté</Badge>
                )}
                <div className="ml-auto flex gap-2">
                    {state && !ready && (
                        <Button type="button" onClick={() => void open("onboarding")} disabled={busy}>
                            {busy && <Loader2 className="animate-spin" />}
                            {state.connected ? "Terminer l'inscription Stripe" : "Connecter mon compte Stripe"}
                        </Button>
                    )}
                    {state?.connected && state.details_submitted && (
                        <Button type="button" variant="outline" onClick={() => void open("dashboard")} disabled={busy}>
                            <ExternalLink /> Tableau de bord Stripe
                        </Button>
                    )}
                </div>
            </div>
        </PageSection>
    );
}

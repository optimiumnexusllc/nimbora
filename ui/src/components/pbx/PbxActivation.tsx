"use client";

import { Building2, Loader2, Plug, Server, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { provisionApiV1PbxProvisionPost } from "@/client/sdk.gen";
import type { ConnectionResponse, PlanAccessResponse } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

/** First screen of the PBX page: platform PBX in one click, or your own. */
export function PbxActivation({
    access,
    pbxName,
    onActivated,
    onConnectOwn,
}: {
    access: PlanAccessResponse | null;
    pbxName: string;
    onActivated: (connection: ConnectionResponse) => void;
    onConnectOwn: () => void;
}) {
    const [busy, setBusy] = useState(false);
    const shared = Boolean(access?.shared && access?.shared_available);
    const dedicated = access ? access.dedicated : true;

    const activate = async () => {
        setBusy(true);
        const response = await provisionApiV1PbxProvisionPost();
        setBusy(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Activation impossible"));
            return;
        }
        toast.success("Téléphonie activée : votre espace est prêt");
        onActivated(response.data);
    };

    if (access && !shared && !dedicated) {
        return (
            <div className="card-weave flex flex-col items-center gap-4 rounded-xl border border-border/60 p-10 text-center" data-testid="pbx-not-in-plan">
                <div className="max-w-xl space-y-2">
                    <h2 className="font-display text-xl font-semibold">La téléphonie d&apos;entreprise n&apos;est pas incluse</h2>
                    <p className="text-sm text-muted-foreground">
                        Votre offre {access.plan_name ? `(${access.plan_name}) ` : ""}ne comprend pas {pbxName}. Choisissez une
                        offre qui l&apos;inclut pour ouvrir des postes, des files d&apos;attente et des numéros.
                    </p>
                </div>
                <Button asChild>
                    <Link href="/subscription">Voir les offres</Link>
                </Button>
            </div>
        );
    }

    return (
        <div className={cn("grid gap-4", shared && dedicated && "md:grid-cols-2")}>
            {shared && (
                <div className="card-weave flex flex-col gap-4 rounded-xl border border-brand-cyan/40 p-6" data-testid="pbx-activate-shared">
                    <div className="flex items-center gap-3">
                        <div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-brand-cyan to-brand-violet text-white">
                            <Building2 className="size-5" />
                        </div>
                        <div>
                            <h2 className="font-display text-lg font-semibold">{pbxName} de la plateforme</h2>
                            <Badge variant="secondary">Recommandé · rien à installer</Badge>
                        </div>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Votre espace téléphonique est créé en quelques secondes sur le PBX de la plateforme : postes,
                        files d&apos;attente, numéros, serveurs vocaux et agents IA, isolés de ceux des autres entreprises.
                    </p>
                    {access?.seats_limit != null && (
                        <p className="flex items-center gap-2 text-sm">
                            <Users className="size-4 text-muted-foreground" />
                            Votre offre comprend {access.seats_limit} poste{access.seats_limit > 1 ? "s" : ""} humain
                            {access.seats_limit > 1 ? "s" : ""}.
                        </p>
                    )}
                    <Button onClick={activate} disabled={busy} className="mt-auto self-start">
                        {busy ? <Loader2 className="animate-spin" /> : <Plug />} Activer la téléphonie
                    </Button>
                </div>
            )}
            {dedicated && (
                <div className="card-weave flex flex-col gap-4 rounded-xl border border-border/60 p-6" data-testid="pbx-connect-own">
                    <div className="flex items-center gap-3">
                        <div className="flex size-11 items-center justify-center rounded-xl bg-muted">
                            <Server className="size-5" />
                        </div>
                        <h2 className="font-display text-lg font-semibold">Votre propre PBX</h2>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Installez {pbxName} sur un serveur dédié avec le kit <code>deploy/pbx</code> (une commande, marque
                        blanche incluse), puis saisissez l&apos;adresse et le compte de service affichés à la fin de
                        l&apos;installation.
                    </p>
                    <Button variant={shared ? "outline" : "default"} onClick={onConnectOwn} className="mt-auto self-start">
                        <Plug /> Connecter mon PBX
                    </Button>
                </div>
            )}
        </div>
    );
}

/** Human seats used by the company against its plan. */
export function SeatsBadge({ access }: { access: PlanAccessResponse | null }) {
    if (!access || access.seats_limit == null || access.seats_used == null) return null;
    const full = access.seats_used >= access.seats_limit;
    return (
        <Badge variant={full ? "destructive" : "secondary"} data-testid="pbx-seats" title="Conseillers du centre intégré et postes du PBX">
            <Users className="mr-1 size-3" /> Postes {access.seats_used} / {access.seats_limit}
        </Badge>
    );
}

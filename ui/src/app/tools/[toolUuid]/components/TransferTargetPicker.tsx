"use client";

import { Building2, Headset, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { transferTargetsApiV1PbxTransferTargetsGet } from "@/client/sdk.gen";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useBrand } from "@/context/BrandContext";
import { useAuth } from "@/lib/auth";
import { enterpriseApi } from "@/lib/enterpriseApi";

export type TransferTarget = {
    destination: string;
    kind: "pbx_queue" | "pbx_extension" | "queue";
    label: string;
    number?: string | null;
};

const GROUPS: { kind: TransferTarget["kind"]; title: string; icon: typeof Users }[] = [
    { kind: "pbx_queue", title: "Files du PBX d'entreprise", icon: Users },
    { kind: "pbx_extension", title: "Postes du PBX d'entreprise", icon: Building2 },
    { kind: "queue", title: "Files du centre d'appels", icon: Headset },
];

/**
 * The company's own human destinations: PBX queues and extensions, and the
 * built-in contact center's queues. Picking one fills the destination; the
 * AI's handoff card follows the caller to whoever answers.
 */
export function TransferTargetPicker({
    value,
    onPick,
}: {
    value: string;
    onPick: (destination: string) => void;
}) {
    const brand = useBrand();
    const { user, loading } = useAuth();
    const [targets, setTargets] = useState<TransferTarget[]>([]);
    const fetched = useRef(false);

    useEffect(() => {
        if (loading || !user || fetched.current) return;
        fetched.current = true;
        void (async () => {
            const found: TransferTarget[] = [];
            const pbx = await transferTargetsApiV1PbxTransferTargetsGet();
            if (!pbx.error && Array.isArray(pbx.data)) found.push(...(pbx.data as TransferTarget[]));
            try {
                const queues = await enterpriseApi.listQueues();
                found.push(
                    ...queues.map((q) => ({ destination: `queue:${q.slug}`, kind: "queue" as const, label: q.name })),
                );
            } catch {
                // contact center not enabled: PBX targets only
            }
            setTargets(found);
        })();
    }, [loading, user]);

    if (targets.length === 0) return null;
    const known = targets.some((t) => t.destination === value);

    return (
        <div className="grid gap-1" data-testid="transfer-target-picker">
            <Select value={known ? value : undefined} onValueChange={onPick}>
                <SelectTrigger aria-label="Choisir une file ou un poste de l'entreprise">
                    <SelectValue placeholder="Ou choisissez une file ou un poste de l'entreprise…" />
                </SelectTrigger>
                <SelectContent>
                    {GROUPS.map(({ kind, title, icon: Icon }) => {
                        const items = targets.filter((t) => t.kind === kind);
                        if (items.length === 0) return null;
                        return (
                            <SelectGroup key={kind}>
                                <SelectLabel className="flex items-center gap-2">
                                    <Icon className="h-3.5 w-3.5" />
                                    {title}
                                </SelectLabel>
                                {items.map((t) => (
                                    <SelectItem key={t.destination} value={t.destination}>
                                        {t.label}
                                        {t.number ? ` · ${t.number}` : ""}
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        );
                    })}
                </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
                Le conseiller qui décroche voit le numéro du client et la fiche de l&apos;agent IA (motif, résumé,
                humeur, informations recueillies) — dans {brand.softphoneName} et dans la supervision.
            </p>
        </div>
    );
}

"use client";

import { Progress } from "@/components/ui/progress";
import { formatLimit, formatPrice, type Subscription } from "@/lib/enterpriseApi";

/** Human calls of the enterprise PBX, counted apart from AI minutes. */
export function HumanMinutes({ subscription }: { subscription: Subscription }) {
    const used = subscription.human_used_minutes ?? 0;
    const included = subscription.human_included_minutes ?? null;
    if (!used && included === null) return null;
    const pct = included ? Math.min(100, (used / included) * 100) : 0;
    return (
        <div className="space-y-2" data-testid="human-minutes">
            <div className="flex justify-between text-sm">
                <span>Minutes des appels humains (téléphonie d&apos;entreprise)</span>
                <span className="font-medium">
                    {used.toLocaleString("fr-FR")} / {formatLimit(included)}
                </span>
            </div>
            {included !== null && <Progress value={pct} />}
            {(subscription.human_overage_minutes ?? 0) > 0 && (
                <p className="text-sm text-muted-foreground">
                    Dépassement : {(subscription.human_overage_minutes ?? 0).toLocaleString("fr-FR")} min (≈{" "}
                    {formatPrice(subscription.estimated_human_overage_cents ?? 0, "eur")})
                </p>
            )}
        </div>
    );
}

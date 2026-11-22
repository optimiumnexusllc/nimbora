"use client";

import { Download, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/lib/auth";
import { enterpriseApi, formatLimit, formatPrice, usageCsv,type UsageLine } from "@/lib/enterpriseApi";

const currentMonth = () => new Date().toISOString().slice(0, 7);

const minutes = (value: number) => value.toLocaleString("fr-FR", { maximumFractionDigits: 1 });

/** Operator console: AI and human minutes of every company, for invoicing. */
export function MonthlyUsageReport() {
    const [month, setMonth] = useState(currentMonth);
    const [lines, setLines] = useState<UsageLine[] | null>(null);
    const [busy, setBusy] = useState(false);
    const { user, loading: authLoading } = useAuth();
    const fetched = useRef(false);

    const load = useCallback(async (wanted: string) => {
        setBusy(true);
        try {
            const result = await enterpriseApi.adminMonthlyUsage(wanted);
            setLines(result.lines);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Consommation indisponible");
        } finally {
            setBusy(false);
        }
    }, []);

    useEffect(() => {
        // Once authentication is ready; the month field reloads on demand.
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void load(month);
    }, [authLoading, user, load, month]);

    const download = () => {
        if (!lines) return;
        const blob = new Blob(["﻿" + usageCsv(lines)], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `consommation-${month}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    };

    const total = (lines ?? []).reduce((sum, line) => sum + line.total_overage_cents, 0);

    return (
        <div className="space-y-4" data-testid="monthly-usage">
            <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                    <Label htmlFor="usage-month">Mois</Label>
                    <Input
                        id="usage-month"
                        type="month"
                        className="w-44"
                        value={month}
                        onChange={(e) => setMonth(e.target.value)}
                    />
                </div>
                <Button variant="outline" onClick={() => void load(month)} disabled={busy || !month}>
                    {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Afficher
                </Button>
                <Button onClick={download} disabled={!lines?.length}>
                    <Download /> Exporter (CSV)
                </Button>
                {lines && (
                    <p className="ml-auto text-sm text-muted-foreground">
                        Dépassements du mois : <span className="font-medium text-foreground">{formatPrice(total, "eur")}</span>
                    </p>
                )}
            </div>
            {lines && lines.length === 0 && (
                <p className="py-6 text-center text-sm text-muted-foreground">Aucune entreprise abonnée.</p>
            )}
            {lines && lines.length > 0 && (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Entreprise</TableHead>
                            <TableHead>Offre</TableHead>
                            <TableHead className="text-right">Minutes IA</TableHead>
                            <TableHead className="text-right">Minutes humaines</TableHead>
                            <TableHead className="text-right">Dépassement</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {lines.map((line) => (
                            <TableRow key={line.organization_id}>
                                <TableCell>
                                    <div className="font-medium">{line.company_name || `#${line.organization_id}`}</div>
                                    <div className="text-xs text-muted-foreground">{line.billing_email}</div>
                                </TableCell>
                                <TableCell>{line.plan_code}</TableCell>
                                <TableCell className="text-right tabular-nums">
                                    {minutes(line.ai_minutes)}{" "}
                                    <span className="text-muted-foreground">/ {formatLimit(line.ai_included_minutes)}</span>
                                </TableCell>
                                <TableCell className="text-right tabular-nums">
                                    {minutes(line.human_minutes)}{" "}
                                    <span className="text-muted-foreground">/ {formatLimit(line.human_included_minutes)}</span>
                                </TableCell>
                                <TableCell className="text-right tabular-nums font-medium">
                                    {formatPrice(line.total_overage_cents, line.currency)}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}
        </div>
    );
}

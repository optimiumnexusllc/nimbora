"use client";

import { Ban, FileUp, PhoneIncoming, PhoneOutgoing, Search, ShieldBan, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    addBlockedNumberApiV1BlockedNumbersPost,
    importBlockedNumbersApiV1BlockedNumbersImportPost,
    listBlockedNumbersApiV1BlockedNumbersGet,
    removeBlockedNumberApiV1BlockedNumbersEntryIdDelete,
} from "@/client/sdk.gen";
import type { BlockedNumberResponse } from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

type Direction = "inbound" | "outbound" | "both";

const DIRECTIONS: Record<Direction, { label: string; hint: string }> = {
    both: { label: "Dans les deux sens", hint: "Jamais décroché, jamais appelé" },
    inbound: { label: "Appels reçus", hint: "Appelant raccroché avant tout agent" },
    outbound: { label: "Appels émis", hint: "Jamais appelé (opposition)" },
};
const SOURCES: Record<string, string> = {
    manual: "Ajouté à la main",
    import: "Import",
    caller_request: "Demande du client",
};

const fmt = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

function DirectionBadge({ direction }: { direction: string }) {
    return (
        <Badge variant="outline" className="gap-1 whitespace-nowrap">
            {direction !== "outbound" && <PhoneIncoming className="size-3" />}
            {direction !== "inbound" && <PhoneOutgoing className="size-3" />}
            {DIRECTIONS[direction as Direction]?.label ?? direction}
        </Badge>
    );
}

export default function BlockedNumbersPage() {
    const { user, loading: authLoading } = useAuth();
    const [items, setItems] = useState<BlockedNumberResponse[] | null>(null);
    const [stats, setStats] = useState({ total: 0, hits: 0, caller_requests: 0 });
    const [search, setSearch] = useState("");
    const [form, setForm] = useState<{ number: string; direction: Direction; reason: string }>({
        number: "",
        direction: "both",
        reason: "",
    });
    const [importErrors, setImportErrors] = useState<{ line: number; value: string; error: string }[]>([]);
    const fileInput = useRef<HTMLInputElement>(null);
    const fetched = useRef(false);

    const load = useCallback(async (query?: string) => {
        const response = await listBlockedNumbersApiV1BlockedNumbersGet({ query: { search: query || undefined } });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Chargement impossible"));
            setItems([]);
            return;
        }
        setItems(response.data.items);
        setStats(response.data.stats);
    }, []);

    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void load();
    }, [authLoading, user, load]);

    useEffect(() => {
        if (!fetched.current) return;
        const timer = setTimeout(() => void load(search.trim()), 300);
        return () => clearTimeout(timer);
    }, [search, load]);

    const add = async () => {
        const response = await addBlockedNumberApiV1BlockedNumbersPost({ body: form });
        if (response.error) {
            toast.error(detailFromError(response.error, "Ajout impossible"));
            return;
        }
        toast.success(`${response.data?.number} bloqué`);
        setForm({ number: "", direction: form.direction, reason: "" });
        void load(search.trim());
    };

    const importFile = async (file: File) => {
        const content = await file.text();
        const response = await importBlockedNumbersApiV1BlockedNumbersImportPost({ body: { content } });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Import impossible"));
            return;
        }
        setImportErrors(response.data.errors as { line: number; value: string; error: string }[]);
        toast.success(`${response.data.imported} numéro(s) importé(s)`);
        void load(search.trim());
    };

    return (
        <PageLayout
            title="Numéros bloqués"
            description="Les appelants refusés et les personnes que vos agents IA n'appellent plus. La liste s'applique partout : PBX, lignes SIP, opérateurs cloud, campagnes et rappels."
        >
            <div className="grid gap-3 sm:grid-cols-3">
                {[
                    { label: "Numéros bloqués", value: stats.total, icon: ShieldBan },
                    { label: "Oppositions des clients", value: stats.caller_requests, icon: PhoneOutgoing, hint: "ajoutées par les agents IA" },
                    { label: "Appels évités", value: stats.hits, icon: Ban },
                ].map((stat) => (
                    <div key={stat.label} className="card-weave flex items-center gap-3 rounded-xl border border-border/60 p-4" data-testid="blocked-stat">
                        <stat.icon className="size-5 text-brand-cyan" />
                        <div>
                            <p className="font-display text-2xl font-semibold">{stat.value}</p>
                            <p className="text-sm text-muted-foreground">
                                {stat.label}
                                {stat.hint && <span className="block text-xs">{stat.hint}</span>}
                            </p>
                        </div>
                    </div>
                ))}
            </div>

            <PageSection
                title="Bloquer un numéro"
                description="Un client qui dit à un agent IA « ne m'appelez plus » est ajouté automatiquement, pour les appels émis."
                actions={
                    <>
                        <input
                            ref={fileInput}
                            type="file"
                            accept=".csv,.txt"
                            className="hidden"
                            data-testid="blocked-import-input"
                            onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) void importFile(file);
                                e.target.value = "";
                            }}
                        />
                        <Button variant="outline" onClick={() => fileInput.current?.click()}>
                            <FileUp /> Importer un CSV
                        </Button>
                    </>
                }
            >
                <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_220px_minmax(0,1.3fr)_auto]">
                    <div className="space-y-1">
                        <Label htmlFor="blocked-number">Numéro</Label>
                        <Input
                            id="blocked-number"
                            placeholder="+225 07 07 11 22 33"
                            value={form.number}
                            onChange={(e) => setForm({ ...form, number: e.target.value })}
                        />
                    </div>
                    <div className="space-y-1">
                        <Label>Sens</Label>
                        <Select value={form.direction} onValueChange={(v) => setForm({ ...form, direction: v as Direction })}>
                            <SelectTrigger aria-label="Sens" className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {(Object.keys(DIRECTIONS) as Direction[]).map((d) => (
                                    <SelectItem key={d} value={d}>
                                        {DIRECTIONS[d].label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="blocked-reason">Motif</Label>
                        <Input
                            id="blocked-reason"
                            placeholder="Démarchage abusif, opposition…"
                            maxLength={255}
                            value={form.reason}
                            onChange={(e) => setForm({ ...form, reason: e.target.value })}
                        />
                    </div>
                    <Button disabled={form.number.trim().length < 3} onClick={() => void add()}>
                        <Ban /> Bloquer
                    </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                    {DIRECTIONS[form.direction].hint}. CSV : <code>numero;motif;sens</code> (sens : entrant, sortant ou les deux).
                </p>
                {importErrors.length > 0 && (
                    <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="blocked-import-errors">
                        <p className="font-medium">Lignes ignorées</p>
                        <ul className="mt-1 space-y-0.5">
                            {importErrors.map((e) => (
                                <li key={e.line}>
                                    Ligne {e.line} ({e.value || "vide"}) : {e.error}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </PageSection>

            <PageSection
                title="Liste"
                toolbar={
                    <div className="relative w-full max-w-sm">
                        <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                        <Input
                            aria-label="Rechercher"
                            className="pl-8"
                            placeholder="Numéro ou motif"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                }
            >
                {items === null ? (
                    <Skeleton className="h-40" />
                ) : items.length === 0 ? (
                    <p className="py-8 text-center text-sm text-muted-foreground">Aucun numéro bloqué.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Numéro</TableHead>
                                <TableHead>Sens</TableHead>
                                <TableHead>Motif</TableHead>
                                <TableHead>Origine</TableHead>
                                <TableHead className="text-right">Appels évités</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {items.map((item) => (
                                <TableRow key={item.id} data-testid="blocked-row">
                                    <TableCell className="font-mono">{item.number}</TableCell>
                                    <TableCell>
                                        <DirectionBadge direction={item.direction} />
                                    </TableCell>
                                    <TableCell className="max-w-xs whitespace-normal break-words text-sm">
                                        {item.reason || "—"}
                                        {item.expires_at && (
                                            <span className="block text-xs text-muted-foreground">jusqu&apos;au {fmt(item.expires_at)}</span>
                                        )}
                                    </TableCell>
                                    <TableCell className="text-sm text-muted-foreground">
                                        {SOURCES[item.source] ?? item.source}
                                        <span className="block text-xs">{fmt(item.created_at)}</span>
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {item.hits}
                                        {item.last_hit_at && <span className="block text-xs text-muted-foreground">dernier : {fmt(item.last_hit_at)}</span>}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            className="text-destructive"
                                            aria-label={`Débloquer ${item.number}`}
                                            onClick={async () => {
                                                if (!window.confirm(`Débloquer le ${item.number} ?`)) return;
                                                const response = await removeBlockedNumberApiV1BlockedNumbersEntryIdDelete({
                                                    path: { entry_id: item.id },
                                                });
                                                if (response.error) {
                                                    toast.error(detailFromError(response.error, "Impossible de débloquer"));
                                                    return;
                                                }
                                                toast.success(`${item.number} débloqué`);
                                                void load(search.trim());
                                            }}
                                        >
                                            <Trash2 /> Débloquer
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>
        </PageLayout>
    );
}

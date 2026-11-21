"use client";

import { ArrowDown, ArrowUp, Cable, CircleCheck, CircleX, Plus, Route, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    createOutboundRouteApiV1PbxOutboundRoutesPost,
    createTrunkApiV1PbxTrunksPost,
    deleteOutboundRouteApiV1PbxOutboundRoutesOutcallIdDelete,
    deleteTrunkApiV1PbxTrunksTrunkIdDelete,
    testDialApiV1PbxOutboundRoutesTestPost,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
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
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";

import type { DialRule, PatternPreset, PbxOutboundRoute, PbxTrunk } from "./types";

type TrunkForm = {
    label: string;
    host: string;
    port: number;
    transport: "udp" | "tcp" | "tls";
    registration: boolean;
    username: string;
    password: string;
    caller_id_format: "+E164" | "E164" | "national";
};
const EMPTY_TRUNK: TrunkForm = {
    label: "",
    host: "",
    port: 5060,
    transport: "udp",
    registration: true,
    username: "",
    password: "",
    caller_id_format: "+E164",
};
const EMPTY_RULE: DialRule = { pattern: "", strip_digits: 0, prefix: "", external_prefix: "", caller_id: "" };

function Registration({ trunk }: { trunk: PbxTrunk }) {
    if (!trunk.registration) return <Badge variant="outline">Par adresse IP</Badge>;
    if (trunk.registered == null) return <Badge variant="outline">État inconnu</Badge>;
    return trunk.registered ? (
        <Badge variant="outline" className="gap-1 border-emerald-500/50 text-emerald-300">
            <CircleCheck className="size-3" /> Enregistrée
        </Badge>
    ) : (
        <Badge variant="outline" className="gap-1 border-red-500/50 text-red-300">
            <CircleX className="size-3" /> Non enregistrée
        </Badge>
    );
}

function TrunkDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
    const [form, setForm] = useState<TrunkForm>(EMPTY_TRUNK);
    const [saving, setSaving] = useState(false);
    useEffect(() => {
        if (open) setForm(EMPTY_TRUNK);
    }, [open]);
    const set = (patch: Partial<TrunkForm>) => setForm((f) => ({ ...f, ...patch }));
    const ready = form.label.trim() && form.host.trim() && (!form.registration || (form.username.trim() && form.password));
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle>Nouvelle ligne opérateur</DialogTitle>
                    <DialogDescription>
                        Les informations SIP fournies par votre opérateur. Les appels qu&apos;il envoie arrivent sur vos
                        numéros ; vos routes sortantes s&apos;en servent pour appeler l&apos;extérieur.
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1 sm:col-span-2">
                        <Label htmlFor="trunk-label">Nom</Label>
                        <Input id="trunk-label" placeholder="Opérateur principal" value={form.label} onChange={(e) => set({ label: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="trunk-host">Serveur de l&apos;opérateur</Label>
                        <Input id="trunk-host" placeholder="sip.operateur.example" value={form.host} onChange={(e) => set({ host: e.target.value })} />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                            <Label htmlFor="trunk-port">Port</Label>
                            <Input id="trunk-port" type="number" value={form.port} onChange={(e) => set({ port: Number(e.target.value) })} />
                        </div>
                        <div className="space-y-1">
                            <Label>Transport</Label>
                            <Select value={form.transport} onValueChange={(v) => set({ transport: v as TrunkForm["transport"], port: v === "tls" ? 5061 : 5060 })}>
                                <SelectTrigger aria-label="Transport" className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="udp">UDP</SelectItem>
                                    <SelectItem value="tcp">TCP</SelectItem>
                                    <SelectItem value="tls">TLS (chiffré)</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <label className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3 sm:col-span-2">
                        <span className="text-sm">
                            <span className="font-medium">S&apos;enregistrer auprès de l&apos;opérateur</span>
                            <span className="block text-muted-foreground">
                                Avec identifiant et mot de passe. Désactivez pour une interconnexion par adresse IP.
                            </span>
                        </span>
                        <Switch checked={form.registration} onCheckedChange={(v) => set({ registration: v })} aria-label="Enregistrement" />
                    </label>
                    <div className="space-y-1">
                        <Label htmlFor="trunk-user">Identifiant SIP</Label>
                        <Input id="trunk-user" autoComplete="off" value={form.username} onChange={(e) => set({ username: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="trunk-password">Mot de passe SIP</Label>
                        <Input
                            id="trunk-password"
                            type="password"
                            autoComplete="new-password"
                            value={form.password}
                            onChange={(e) => set({ password: e.target.value })}
                        />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                        <Label>Format du numéro présenté</Label>
                        <Select value={form.caller_id_format} onValueChange={(v) => set({ caller_id_format: v as TrunkForm["caller_id_format"] })}>
                            <SelectTrigger aria-label="Format du numéro présenté" className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="+E164">International avec + (+225 27…)</SelectItem>
                                <SelectItem value="E164">International sans + (225 27…)</SelectItem>
                                <SelectItem value="national">National (27…)</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button
                        disabled={!ready || saving}
                        onClick={async () => {
                            setSaving(true);
                            const response = await createTrunkApiV1PbxTrunksPost({ body: form });
                            setSaving(false);
                            if (response.error) {
                                toast.error(detailFromError(response.error, "Création impossible"));
                                return;
                            }
                            toast.success(`Ligne « ${form.label} » créée`);
                            onOpenChange(false);
                            onDone();
                        }}
                    >
                        <Cable /> Créer la ligne
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function RouteDialog({
    open,
    onOpenChange,
    trunks,
    presets,
    onDone,
}: {
    open: boolean;
    onOpenChange: (o: boolean) => void;
    trunks: PbxTrunk[];
    presets: PatternPreset[];
    onDone: () => void;
}) {
    const [name, setName] = useState("");
    const [order, setOrder] = useState<number[]>([]);
    const [rules, setRules] = useState<DialRule[]>([{ ...EMPTY_RULE }]);
    const [internalCallerId, setInternalCallerId] = useState(false);
    const [dialled, setDialled] = useState("");
    const [result, setResult] = useState<string | null>(null);
    useEffect(() => {
        if (!open) return;
        setName("");
        setOrder(trunks[0] ? [trunks[0].id] : []);
        setRules([{ ...EMPTY_RULE }]);
        setInternalCallerId(false);
        setDialled("");
        setResult(null);
    }, [open, trunks]);
    const setRule = (index: number, patch: Partial<DialRule>) => setRules((r) => r.map((x, i) => (i === index ? { ...x, ...patch } : x)));
    const move = (index: number, delta: number) =>
        setOrder((o) => {
            const next = [...o];
            const [item] = next.splice(index, 1);
            next.splice(index + delta, 0, item);
            return next;
        });
    const label = (id: number) => trunks.find((t) => t.id === id)?.label ?? `Ligne ${id}`;
    const ready = name.trim() && order.length > 0 && rules.every((r) => r.pattern.trim());

    const test = async () => {
        const response = await testDialApiV1PbxOutboundRoutesTestPost({ body: { dialled, rules: rules.filter((r) => r.pattern.trim()) } });
        if (response.error || !response.data) {
            setResult(detailFromError(response.error, "Test impossible"));
            return;
        }
        const data = response.data as { matched: boolean; rule_index: number | null; sent: string | null; caller_id: string | null };
        setResult(
            data.matched
                ? `Motif ${rules[data.rule_index ?? 0].pattern} → l'opérateur reçoit ${data.sent}${data.caller_id ? `, présenté ${data.caller_id}` : ""}`
                : "Aucun motif ne correspond : l'appel ne sortira pas par cette route.",
        );
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl">
                <DialogHeader>
                    <DialogTitle>Nouvelle route sortante</DialogTitle>
                    <DialogDescription>
                        Les numéros composés qui correspondent à un motif sortent par la première ligne ; la suivante
                        prend le relais si elle échoue.
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                    <div className="space-y-1">
                        <Label htmlFor="route-name">Nom</Label>
                        <Input id="route-name" placeholder="Appels nationaux" value={name} onChange={(e) => setName(e.target.value)} />
                    </div>
                    <div className="space-y-2">
                        <Label>Lignes, dans l&apos;ordre d&apos;essai</Label>
                        <div className="grid gap-1 sm:grid-cols-2">
                            {trunks.map((t) => (
                                <label key={t.id} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40">
                                    <Checkbox
                                        aria-label={t.label}
                                        checked={order.includes(t.id)}
                                        onCheckedChange={(v) => setOrder((o) => (v ? [...o, t.id] : o.filter((x) => x !== t.id)))}
                                    />
                                    {t.label}
                                </label>
                            ))}
                        </div>
                        {order.length > 1 && (
                            <ol className="space-y-1 rounded-md border border-border/60 p-2 text-sm" data-testid="trunk-order">
                                {order.map((id, index) => (
                                    <li key={id} className="flex items-center gap-2">
                                        <Badge variant="outline">{index + 1}</Badge> {label(id)}
                                        <span className="ml-auto flex">
                                            <Button size="icon" variant="ghost" aria-label={`Monter ${label(id)}`} disabled={index === 0} onClick={() => move(index, -1)}>
                                                <ArrowUp />
                                            </Button>
                                            <Button
                                                size="icon"
                                                variant="ghost"
                                                aria-label={`Descendre ${label(id)}`}
                                                disabled={index === order.length - 1}
                                                onClick={() => move(index, 1)}
                                            >
                                                <ArrowDown />
                                            </Button>
                                        </span>
                                    </li>
                                ))}
                            </ol>
                        )}
                    </div>
                    <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Label className="mr-auto">Motifs de numérotation</Label>
                            {presets.map((p) => (
                                <Button
                                    key={p.id}
                                    size="sm"
                                    variant="outline"
                                    title={p.label}
                                    onClick={() =>
                                        setRules((r) => {
                                            const empty = r.findIndex((x) => !x.pattern.trim());
                                            const rule = { ...EMPTY_RULE, pattern: p.pattern };
                                            return empty >= 0 ? r.map((x, i) => (i === empty ? rule : x)) : [...r, rule];
                                        })
                                    }
                                >
                                    {p.pattern}
                                </Button>
                            ))}
                        </div>
                        <p className="text-xs text-muted-foreground">
                            « _ » puis X = un chiffre, N = 2 à 9, Z = 1 à 9, [1-5] = une plage, « . » = la suite du numéro.
                        </p>
                        {rules.map((rule, index) => (
                            <div key={index} className="grid items-end gap-2 rounded-lg border border-border/60 p-2 sm:grid-cols-[1.3fr_80px_1fr_1.4fr_36px]" data-testid="dial-rule">
                                <div className="space-y-1">
                                    <Label className="text-xs">Motif</Label>
                                    <Input aria-label={`Motif ${index + 1}`} className="font-mono" placeholder="_0XXXXXXXXX" value={rule.pattern} onChange={(e) => setRule(index, { pattern: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Retirer</Label>
                                    <Input aria-label={`Chiffres retirés ${index + 1}`} type="number" min={0} max={20} value={rule.strip_digits} onChange={(e) => setRule(index, { strip_digits: Number(e.target.value) })} />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Ajouter devant</Label>
                                    <Input aria-label={`Préfixe opérateur ${index + 1}`} className="font-mono" placeholder="+" value={rule.external_prefix} onChange={(e) => setRule(index, { external_prefix: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Numéro présenté</Label>
                                    <Input aria-label={`Numéro présenté ${index + 1}`} placeholder="+225 27 …" value={rule.caller_id} onChange={(e) => setRule(index, { caller_id: e.target.value })} />
                                </div>
                                <Button size="icon" variant="ghost" aria-label={`Retirer le motif ${index + 1}`} disabled={rules.length === 1} onClick={() => setRules((r) => r.filter((_, i) => i !== index))}>
                                    <X />
                                </Button>
                            </div>
                        ))}
                        <Button size="sm" variant="ghost" onClick={() => setRules((r) => [...r, { ...EMPTY_RULE }])}>
                            <Plus /> Ajouter un motif
                        </Button>
                    </div>
                    <div className="space-y-2 rounded-lg border border-dashed border-border/60 p-3">
                        <Label htmlFor="dial-test">Tester un numéro</Label>
                        <div className="flex gap-2">
                            <Input id="dial-test" className="font-mono" placeholder="0033612345678" value={dialled} onChange={(e) => setDialled(e.target.value)} />
                            <Button variant="outline" disabled={!dialled.trim() || !rules.some((r) => r.pattern.trim())} onClick={() => void test()}>
                                Tester
                            </Button>
                        </div>
                        {result && <p className="text-sm" data-testid="dial-result">{result}</p>}
                    </div>
                    <label className="flex items-center justify-between gap-3 text-sm">
                        Présenter le numéro interne de l&apos;appelant quand l&apos;opérateur l&apos;accepte
                        <Switch checked={internalCallerId} onCheckedChange={setInternalCallerId} aria-label="Numéro interne présenté" />
                    </label>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button
                        disabled={!ready}
                        onClick={async () => {
                            const response = await createOutboundRouteApiV1PbxOutboundRoutesPost({
                                body: { name, trunk_ids: order, rules, internal_caller_id: internalCallerId },
                            });
                            if (response.error) {
                                toast.error(detailFromError(response.error, "Création impossible"));
                                return;
                            }
                            toast.success(`Route « ${name} » créée`);
                            onOpenChange(false);
                            onDone();
                        }}
                    >
                        <Route /> Créer la route
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export function TrunksTab({
    trunks,
    routes,
    presets,
    error,
    onChanged,
}: {
    trunks: PbxTrunk[];
    routes: PbxOutboundRoute[];
    presets: PatternPreset[];
    error?: string | null;
    onChanged: () => void;
}) {
    const [addingTrunk, setAddingTrunk] = useState(false);
    const [addingRoute, setAddingRoute] = useState(false);
    const remove = async (action: () => Promise<{ error?: unknown }>, success: string) => {
        const response = await action();
        if (response.error) {
            toast.error(detailFromError(response.error, "Suppression impossible"));
            return;
        }
        toast.success(success);
        onChanged();
    };
    return (
        <div className="space-y-4">
            <PageSection
                title="Lignes opérateurs"
                description="Les liaisons SIP avec vos opérateurs : elles apportent vos numéros publics et emportent vos appels sortants."
                actions={
                    <Button onClick={() => setAddingTrunk(true)}>
                        <Cable /> Ajouter une ligne
                    </Button>
                }
            >
                {error && <p className="mb-3 text-sm text-amber-300">État d&apos;enregistrement indisponible : {error}</p>}
                {trunks.length === 0 ? (
                    <p className="py-8 text-center text-sm text-muted-foreground">Aucune ligne opérateur.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Ligne</TableHead>
                                <TableHead>Opérateur</TableHead>
                                <TableHead>État</TableHead>
                                <TableHead>Appels</TableHead>
                                <TableHead>Routes</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {trunks.map((t) => (
                                <TableRow key={t.id} data-testid="pbx-trunk">
                                    <TableCell className="font-medium">{t.label}</TableCell>
                                    <TableCell className="font-mono text-sm">
                                        {t.host ?? "—"}
                                        {t.username && <span className="block text-xs text-muted-foreground">{t.username}</span>}
                                    </TableCell>
                                    <TableCell>
                                        <Registration trunk={t} />
                                    </TableCell>
                                    <TableCell>{t.current_calls}</TableCell>
                                    <TableCell className="text-sm text-muted-foreground">{t.outcalls.join(", ") || "—"}</TableCell>
                                    <TableCell className="text-right">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            className="text-destructive"
                                            aria-label={`Supprimer ${t.label}`}
                                            onClick={() => {
                                                if (window.confirm(`Supprimer la ligne « ${t.label} » ?`))
                                                    void remove(() => deleteTrunkApiV1PbxTrunksTrunkIdDelete({ path: { trunk_id: t.id } }), "Ligne supprimée");
                                            }}
                                        >
                                            <Trash2 />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <PageSection
                title="Routes sortantes"
                description="Quels numéros composés partent par quelles lignes, avec quel numéro présenté."
                actions={
                    <Button variant="outline" disabled={trunks.length === 0} onClick={() => setAddingRoute(true)}>
                        <Route /> Nouvelle route
                    </Button>
                }
            >
                {routes.length === 0 ? (
                    <p className="py-8 text-center text-sm text-muted-foreground">
                        Aucune route sortante{trunks.length === 0 ? " : ajoutez d'abord une ligne opérateur" : ""}.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {routes.map((r) => (
                            <div key={r.id} className="flex min-w-0 flex-wrap items-center gap-3 rounded-lg border border-border/60 p-3" data-testid="pbx-route">
                                <div className="min-w-0 flex-1">
                                    <p className="font-medium">{r.name}</p>
                                    <p className="text-sm text-muted-foreground">
                                        {r.trunks.map((t, i) => `${i + 1}. ${t.label}`).join("  →  ")}
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-1">
                                    {r.rules.map((rule) => (
                                        <Badge key={rule.pattern} variant="outline" className="font-mono" title={rule.caller_id ? `Présenté ${rule.caller_id}` : undefined}>
                                            {rule.pattern}
                                            {rule.caller_id && <span className="ml-1 text-muted-foreground">· {rule.caller_id}</span>}
                                        </Badge>
                                    ))}
                                </div>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="text-destructive"
                                    aria-label={`Supprimer ${r.name}`}
                                    onClick={() => {
                                        if (window.confirm(`Supprimer la route « ${r.name} » ?`))
                                            void remove(
                                                () => deleteOutboundRouteApiV1PbxOutboundRoutesOutcallIdDelete({ path: { outcall_id: r.id } }),
                                                "Route supprimée",
                                            );
                                    }}
                                >
                                    <Trash2 />
                                </Button>
                            </div>
                        ))}
                    </div>
                )}
            </PageSection>

            <TrunkDialog open={addingTrunk} onOpenChange={setAddingTrunk} onDone={onChanged} />
            <RouteDialog open={addingRoute} onOpenChange={setAddingRoute} trunks={trunks} presets={presets} onDone={onChanged} />
        </div>
    );
}

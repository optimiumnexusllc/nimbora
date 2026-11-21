"use client";

import {
    Brain,
    Copy,
    Globe,
    KeyRound,
    MessageCircle,
    Phone,
    PhoneIncoming,
    PhoneOutgoing,
    Plus,
    RefreshCw,
    Search,
    Trash2,
    Users,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    readIdentitySecretApiV1CustomersIdentityGet,
    rotateIdentityApiV1CustomersIdentityRotatePost,
} from "@/client/sdk.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { type Customer, type CustomerDetail, enterpriseApi } from "@/lib/enterpriseApi";
import { cn } from "@/lib/utils";

const SENTIMENT_LABEL: Record<string, { label: string; className: string }> = {
    positive: { label: "Satisfait", className: "text-emerald-400" },
    neutral: { label: "Neutre", className: "text-slate-400" },
    frustrated: { label: "Agacé", className: "text-amber-400" },
    angry: { label: "En colère", className: "text-red-400" },
};

const CHANNELS: Record<string, { label: string; className: string }> = {
    phone: { label: "Téléphone", className: "border-sky-500/40 text-sky-300" },
    whatsapp: { label: "WhatsApp", className: "border-emerald-500/40 text-emerald-300" },
    web: { label: "Chat web", className: "border-violet-500/40 text-violet-300" },
};

function ChannelIcon({ channel, direction }: { channel: string | null; direction: string | null }) {
    if (channel === "whatsapp") return <MessageCircle className="size-3.5 text-emerald-400" />;
    if (channel === "web") return <Globe className="size-3.5 text-violet-400" />;
    return direction === "outbound" ? <PhoneOutgoing className="size-3.5" /> : <PhoneIncoming className="size-3.5" />;
}

const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "—";

function CustomerSheet({
    customerId,
    onClose,
    onChanged,
}: {
    customerId: number | null;
    onClose: () => void;
    onChanged: () => void;
}) {
    const [detail, setDetail] = useState<CustomerDetail | null>(null);
    const [name, setName] = useState("");
    const [notes, setNotes] = useState("");
    const [tags, setTags] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (customerId === null) return;
        setDetail(null);
        enterpriseApi
            .getCustomer(customerId)
            .then((d) => {
                setDetail(d);
                setName(d.name ?? "");
                setNotes(d.notes ?? "");
                setTags(d.tags.join(", "));
            })
            .catch((e) => toast.error(e instanceof Error ? e.message : "Chargement impossible"));
    }, [customerId]);

    const save = async () => {
        if (!detail) return;
        setSaving(true);
        try {
            await enterpriseApi.updateCustomer(detail.id, {
                name: name.trim() || null,
                notes: notes.trim() || null,
                tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
            });
            toast.success("Fiche client enregistrée");
            onChanged();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Enregistrement impossible");
        } finally {
            setSaving(false);
        }
    };

    const forget = async () => {
        if (!detail) return;
        if (
            !window.confirm(
                `Effacer définitivement la fiche de ${detail.name || detail.phone} et tout son historique ? (droit à l'oubli)`,
            )
        )
            return;
        try {
            await enterpriseApi.forgetCustomer(detail.id);
            toast.success("Fiche et historique effacés");
            onChanged();
            onClose();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Suppression impossible");
        }
    };

    return (
        <Sheet open={customerId !== null} onOpenChange={(o) => !o && onClose()}>
            <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
                <SheetHeader>
                    <SheetTitle className="font-display">{detail?.name || detail?.phone || "Client"}</SheetTitle>
                    <SheetDescription>
                        {detail ? `${detail.phone} · ${detail.total_calls} échange(s) · client depuis le ${fmt(detail.first_seen_at)}` : ""}
                    </SheetDescription>
                </SheetHeader>
                {!detail ? (
                    <Skeleton className="m-4 h-64" />
                ) : (
                    <div className="space-y-6 px-4 pb-8">
                        <div className="space-y-3">
                            <div className="space-y-1">
                                <Label htmlFor="c-name">Nom</Label>
                                <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="c-notes">Notes de l&apos;équipe (lues par les agents IA)</Label>
                                <Textarea id="c-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="c-tags">Étiquettes (séparées par des virgules)</Label>
                                <Input id="c-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="vip, grossiste" />
                            </div>
                            <div className="flex gap-2">
                                <Button onClick={save} disabled={saving}>
                                    Enregistrer
                                </Button>
                                <Button variant="ghost" className="text-destructive" onClick={forget}>
                                    <Trash2 /> Droit à l&apos;oubli
                                </Button>
                            </div>
                        </div>

                        {Object.keys(detail.attributes).length > 0 && (
                            <div>
                                <h3 className="mb-2 text-sm font-semibold">Ce que les agents ont appris</h3>
                                <dl className="grid grid-cols-2 gap-2 text-sm">
                                    {Object.entries(detail.attributes).map(([k, v]) => (
                                        <div key={k} className="rounded-md border border-border/60 px-3 py-2">
                                            <dt className="text-xs text-muted-foreground">{k.replace(/_/g, " ")}</dt>
                                            <dd className="font-medium">{String(v)}</dd>
                                        </div>
                                    ))}
                                </dl>
                            </div>
                        )}

                        <div>
                            <h3 className="mb-3 text-sm font-semibold">Historique des échanges (tous canaux)</h3>
                            {detail.interactions.length === 0 ? (
                                <p className="text-sm text-muted-foreground">Aucun échange enregistré.</p>
                            ) : (
                                <ol className="relative space-y-4 border-l border-border/60 pl-5">
                                    {detail.interactions.map((i) => {
                                        const s = i.sentiment ? SENTIMENT_LABEL[i.sentiment] : null;
                                        return (
                                            <li key={i.id} className="relative">
                                                <span className="absolute -left-[27px] top-1 flex size-3.5 items-center justify-center rounded-full bg-gradient-to-br from-brand-cyan to-brand-violet" />
                                                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                                    <ChannelIcon channel={i.channel} direction={i.direction} />
                                                    {fmt(i.created_at)}
                                                    {CHANNELS[i.channel ?? "phone"] && (
                                                        <Badge
                                                            variant="outline"
                                                            className={cn("px-1.5 py-0 text-[10px]", CHANNELS[i.channel ?? "phone"].className)}
                                                        >
                                                            {CHANNELS[i.channel ?? "phone"].label}
                                                        </Badge>
                                                    )}
                                                    {i.agent_name && <span>· {i.agent_name}</span>}
                                                    {i.duration_seconds ? (
                                                        <span>· {Math.max(1, Math.round(i.duration_seconds / 60))} min</span>
                                                    ) : null}
                                                    {s && <span className={s.className}>· {s.label}</span>}
                                                </div>
                                                <p className="mt-1 text-sm">{i.summary || "Pas de résumé."}</p>
                                                <div className="mt-1 flex flex-wrap gap-1">
                                                    {i.outcome && <Badge variant="secondary">{i.outcome}</Badge>}
                                                    {i.transferred_to_queue && (
                                                        <Badge variant="secondary">→ équipe {i.transferred_to_queue}</Badge>
                                                    )}
                                                </div>
                                            </li>
                                        );
                                    })}
                                </ol>
                            )}
                        </div>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

function snippet(secret: string): string {
    return `// Sur votre serveur (jamais dans le navigateur) — Node.js
const crypto = require("crypto");
const NIMBORA_IDENTITY_SECRET = "${secret}";

// Numéro au format international, sans espaces : +2250700112233
function nimboraSignature(phone) {
  return crypto.createHmac("sha256", NIMBORA_IDENTITY_SECRET).update(phone).digest("hex");
}

// Puis dans la page, pour le client connecté :
js.setAttribute("data-nimbora-context", JSON.stringify({
  customer_phone: "<%= client.phone %>",
  customer_signature: "<%= nimboraSignature(client.phone) %>"
}));`;
}

function WebIdentityDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
    const [secret, setSecret] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!open || secret) return;
        readIdentitySecretApiV1CustomersIdentityGet().then((response) => {
            if (response.error) {
                toast.error(detailFromError(response.error, "Secret indisponible"));
                return;
            }
            setSecret(response.data?.secret ?? null);
        });
    }, [open, secret]);

    const rotate = async () => {
        if (!window.confirm("Générer un nouveau secret ? Les signatures actuelles cesseront d'être reconnues.")) return;
        setBusy(true);
        const response = await rotateIdentityApiV1CustomersIdentityRotatePost();
        setBusy(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Renouvellement impossible"));
            return;
        }
        setSecret(response.data?.secret ?? null);
        toast.success("Nouveau secret généré");
    };

    const copy = async (text: string, what: string) => {
        try {
            await navigator.clipboard.writeText(text);
            toast.success(`${what} copié`);
        } catch {
            toast.error("Copie impossible");
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-2xl">
                <DialogHeader className="min-w-0">
                    <DialogTitle>Chat web : reconnaître vos clients connectés</DialogTitle>
                    <DialogDescription>
                        Sur votre site, un visiteur peut écrire n&apos;importe quel numéro. Pour que l&apos;agent reprenne
                        l&apos;historique d&apos;un client (appels, WhatsApp), votre serveur signe le numéro du client
                        connecté avec ce secret. Sans signature valide, le chat reste anonyme.
                    </DialogDescription>
                </DialogHeader>
                {!secret ? (
                    <Skeleton className="h-40" />
                ) : (
                    <div className="min-w-0 space-y-4">
                        <div className="space-y-1">
                            <Label>Secret d&apos;identité (à garder côté serveur)</Label>
                            <div className="flex gap-2">
                                <Input readOnly value={secret} className="min-w-0 font-mono text-xs" data-testid="identity-secret" />
                                <Button variant="outline" size="icon" aria-label="Copier le secret" onClick={() => copy(secret, "Secret")}>
                                    <Copy />
                                </Button>
                            </div>
                        </div>
                        <div className="space-y-1">
                            <div className="flex items-center justify-between">
                                <Label>Exemple d&apos;intégration</Label>
                                <Button variant="ghost" size="sm" onClick={() => copy(snippet(secret), "Exemple")}>
                                    <Copy /> Copier
                                </Button>
                            </div>
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border/60 bg-muted/40 p-3 text-xs">
                                {snippet(secret)}
                            </pre>
                        </div>
                    </div>
                )}
                <DialogFooter>
                    <Button variant="ghost" className="text-destructive" onClick={rotate} disabled={busy || !secret}>
                        <RefreshCw /> Renouveler le secret
                    </Button>
                    <Button onClick={() => onOpenChange(false)}>Fermer</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function CustomersPage() {
    const { user, loading } = useAuth();
    const [customers, setCustomers] = useState<Customer[] | null>(null);
    const [total, setTotal] = useState(0);
    const [enabled, setEnabled] = useState(true);
    const [query, setQuery] = useState("");
    const [selected, setSelected] = useState<number | null>(null);
    const [creating, setCreating] = useState(false);
    const [identityOpen, setIdentityOpen] = useState(false);
    const [newPhone, setNewPhone] = useState("");
    const [newName, setNewName] = useState("");
    const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

    const load = useCallback(async (q: string) => {
        try {
            const res = await enterpriseApi.listCustomers(q);
            setCustomers(res.customers);
            setTotal(res.total);
            setEnabled(res.memory_enabled);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Chargement impossible");
        }
    }, []);

    useEffect(() => {
        if (loading || !user) return;
        if (debounce.current) clearTimeout(debounce.current);
        debounce.current = setTimeout(() => void load(query), 250);
    }, [loading, user, load, query]);

    const toggleMemory = async (value: boolean) => {
        setEnabled(value);
        try {
            await enterpriseApi.setMemoryEnabled(value);
            toast.success(value ? "Mémoire client activée" : "Mémoire client désactivée");
        } catch (e) {
            setEnabled(!value);
            toast.error(e instanceof Error ? e.message : "Modification impossible");
        }
    };

    const create = async () => {
        try {
            const c = await enterpriseApi.createCustomer({ phone: newPhone, name: newName || undefined });
            setCreating(false);
            setNewPhone("");
            setNewName("");
            await load(query);
            setSelected(c.id);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : "Création impossible");
        }
    };

    return (
        <PageLayout
            title="Clients"
            description="La mémoire de vos agents : chaque appelant est reconnu, son historique est repris là où il s'était arrêté."
            actions={
                <Button onClick={() => setCreating(true)}>
                    <Plus /> Ajouter un client
                </Button>
            }
        >
            <div className="card-weave flex flex-wrap items-center gap-4 rounded-xl border border-border/60 p-4">
                <div className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-violet to-brand-cyan text-white">
                    <Brain className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                    <p className="font-medium">Mémoire client</p>
                    <p className="text-sm text-muted-foreground">
                        Les agents IA reconnaissent le client au téléphone, sur WhatsApp et sur le chat web,
                        le saluent par son nom et reprennent l&apos;historique de tous les canaux.
                    </p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setIdentityOpen(true)}>
                    <KeyRound /> Chat web : clients identifiés
                </Button>
                <Switch checked={enabled} onCheckedChange={toggleMemory} aria-label="Activer la mémoire client" />
            </div>

            <PageSection
                title={
                    <span className="flex items-center gap-2">
                        <Users className="size-5" /> Fiches clients ({total})
                    </span>
                }
                toolbar={
                    <div className="relative max-w-sm">
                        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                            className="pl-9"
                            placeholder="Nom, numéro ou note…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                    </div>
                }
            >
                {customers === null ? (
                    <Skeleton className="h-40 w-full" />
                ) : customers.length === 0 ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-center text-sm text-muted-foreground">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src="/brand/empty-state.svg" alt="" className="h-24" />
                        {query
                            ? "Aucun client ne correspond à cette recherche."
                            : "Les fiches apparaîtront automatiquement après les premiers appels."}
                    </div>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Client</TableHead>
                                <TableHead>Dernier échange</TableHead>
                                <TableHead className="text-right">Échanges</TableHead>
                                <TableHead>Vu le</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {customers.map((c) => {
                                const s = c.last_sentiment ? SENTIMENT_LABEL[c.last_sentiment] : null;
                                return (
                                    <TableRow key={c.id} className="cursor-pointer" onClick={() => setSelected(c.id)}>
                                        <TableCell>
                                            <div className="font-medium">{c.name || "Inconnu"}</div>
                                            <div className="flex items-center gap-1 font-mono text-xs text-muted-foreground">
                                                <Phone className="size-3" /> {c.phone}
                                            </div>
                                            {c.tags.length > 0 && (
                                                <div className="mt-1 flex flex-wrap gap-1">
                                                    {c.tags.map((t) => (
                                                        <Badge key={t} variant="secondary" className="text-[10px]">
                                                            {t}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            )}
                                        </TableCell>
                                        <TableCell className="max-w-md">
                                            <p className="line-clamp-2 text-sm">{c.last_summary || "—"}</p>
                                            {s && <span className={cn("text-xs", s.className)}>{s.label}</span>}
                                        </TableCell>
                                        <TableCell className="text-right font-display text-lg font-semibold">
                                            {c.total_calls}
                                        </TableCell>
                                        <TableCell className="text-sm text-muted-foreground">{fmt(c.last_seen_at)}</TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <WebIdentityDialog open={identityOpen} onOpenChange={setIdentityOpen} />

            <CustomerSheet customerId={selected} onClose={() => setSelected(null)} onChanged={() => void load(query)} />

            <Dialog open={creating} onOpenChange={setCreating}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Nouveau client</DialogTitle>
                        <DialogDescription>
                            Utile pour préparer un client important avant son premier appel.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="space-y-1">
                            <Label htmlFor="n-phone">Numéro</Label>
                            <Input id="n-phone" placeholder="+227 90 00 00 00" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="n-name">Nom</Label>
                            <Input id="n-name" value={newName} onChange={(e) => setNewName(e.target.value)} />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreating(false)}>
                            Annuler
                        </Button>
                        <Button onClick={create} disabled={!newPhone.trim()}>
                            Créer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageLayout>
    );
}

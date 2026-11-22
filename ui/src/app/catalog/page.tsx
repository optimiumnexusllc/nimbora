"use client";

import { Download, FileUp, Package, Pencil, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    agentPreviewApiV1CatalogAgentPreviewPost,
    createItemApiV1CatalogItemsPost,
    deleteItemApiV1CatalogItemsItemIdDelete,
    exportItemsApiV1CatalogExportCsvGet,
    importItemsApiV1CatalogImportPost,
    listItemsApiV1CatalogItemsGet,
    updateItemApiV1CatalogItemsItemIdPut,
    updateStockApiV1CatalogItemsItemIdStockPatch,
} from "@/client/sdk.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { type CatalogForm, type CatalogItem, download, EMPTY_FORM, fromForm, KINDS, toForm } from "@/lib/catalog";

const ALL = "__all__";

export default function CatalogPage() {
    const { user, loading: authLoading } = useAuth();
    const fetched = useRef(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const [items, setItems] = useState<CatalogItem[] | null>(null);
    const [total, setTotal] = useState(0);
    const [categories, setCategories] = useState<string[]>([]);
    const [query, setQuery] = useState("");
    const [kind, setKind] = useState(ALL);
    const [category, setCategory] = useState(ALL);
    const [editing, setEditing] = useState<{ id: number | null; form: CatalogForm } | null>(null);
    const [preview, setPreview] = useState<{ query: string; budget: string; result: string | null }>({ query: "", budget: "", result: null });

    const load = useCallback(async () => {
        const response = await listItemsApiV1CatalogItemsGet({
            query: { q: query, kind: kind === ALL ? null : kind, category: category === ALL ? null : category, limit: 200 },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Catalogue indisponible"));
            return;
        }
        const data = response.data as unknown as { items: CatalogItem[]; total: number; categories: string[] };
        setItems(data.items);
        setTotal(data.total);
        setCategories(data.categories);
    }, [query, kind, category]);

    useEffect(() => {
        if (authLoading || !user) return;
        const timer = setTimeout(() => void load(), fetched.current ? 250 : 0);
        fetched.current = true;
        return () => clearTimeout(timer);
    }, [authLoading, user, load]);

    const save = async () => {
        if (!editing) return;
        const body = fromForm(editing.form);
        const response = editing.id === null ? await createItemApiV1CatalogItemsPost({ body }) : await updateItemApiV1CatalogItemsItemIdPut({ path: { item_id: editing.id }, body });
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        toast.success(editing.id === null ? "Article ajouté" : "Article enregistré");
        setEditing(null);
        void load();
    };

    const importFile = async (file: File) => {
        const response = await importItemsApiV1CatalogImportPost({ body: { file } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Import impossible"));
            return;
        }
        const report = response.data as unknown as { created: number; updated: number; errors: { line: number; message: string }[] };
        toast.success(`${report.created} ajouté(s), ${report.updated} mis à jour`);
        if (report.errors.length) toast.error(`Lignes ignorées : ${report.errors.map((e) => `${e.line} (${e.message})`).join(", ")}`);
        void load();
    };

    const runPreview = async () => {
        const response = await agentPreviewApiV1CatalogAgentPreviewPost({
            body: { query: preview.query, max_price: preview.budget ? Number(preview.budget.replace(/\s/g, "")) : null, available_only: true },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Essai impossible"));
            return;
        }
        const result = response.data as unknown as { items: { name: string; price: string; availability: string }[]; total: number; hint?: string };
        setPreview({
            ...preview,
            result: result.items.length ? result.items.map((i) => `${i.name} — ${i.price} — ${i.availability}`).join("\n") : "Rien ne correspond : l'agent le dira sans inventer.",
        });
    };

    const set = (patch: Partial<CatalogForm>) => editing && setEditing({ ...editing, form: { ...editing.form, ...patch } });

    return (
        <PageLayout
            title="Catalogue"
            description="Ce que vous vendez ou louez : vos agents le cherchent pendant les appels avec l'outil « Rechercher dans le catalogue » et n'annoncent que ce qu'ils y trouvent."
            actions={
                <div className="flex flex-wrap gap-2">
                    <input
                        ref={fileInput}
                        type="file"
                        accept=".csv,text/csv"
                        className="hidden"
                        data-testid="catalog-file"
                        onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) void importFile(file);
                            e.target.value = "";
                        }}
                    />
                    <Button variant="outline" onClick={() => fileInput.current?.click()}>
                        <FileUp /> Importer un CSV
                    </Button>
                    <Button
                        variant="outline"
                        onClick={async () => {
                            const response = await exportItemsApiV1CatalogExportCsvGet({ parseAs: "text" });
                            if (response.error) toast.error(detailFromError(response.error, "Export impossible"));
                            else download("catalogue.csv", response.data as unknown as string);
                        }}
                    >
                        <Download /> Exporter
                    </Button>
                    <Button onClick={() => setEditing({ id: null, form: EMPTY_FORM })}>
                        <Plus /> Ajouter
                    </Button>
                </div>
            }
        >
            <div className="space-y-6">
                <PageSection title={`${total} article${total > 1 ? "s" : ""}`} description="Colonnes du CSV : nom, reference, type, categorie, description, prix, devise, unite, stock, disponible, url ; toute autre colonne devient une caractéristique. Une référence connue met l'article à jour.">
                    <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_12rem_12rem]">
                        <label className="relative">
                            <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
                            <Input aria-label="Rechercher dans le catalogue" className="pl-9" placeholder="Nom, référence, caractéristique…" value={query} onChange={(e) => setQuery(e.target.value)} />
                        </label>
                        <Select value={kind} onValueChange={setKind}>
                            <SelectTrigger aria-label="Type">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={ALL}>Tous les types</SelectItem>
                                {KINDS.map(([value, label]) => (
                                    <SelectItem key={value} value={value}>
                                        {label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Select value={category} onValueChange={setCategory}>
                            <SelectTrigger aria-label="Catégorie">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={ALL}>Toutes les catégories</SelectItem>
                                {categories.map((c) => (
                                    <SelectItem key={c} value={c}>
                                        {c}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    {items === null ? (
                        <p className="py-8 text-center text-sm text-muted-foreground">Chargement…</p>
                    ) : items.length === 0 ? (
                        <div className="py-10 text-center text-sm text-muted-foreground">
                            <Package className="mx-auto mb-2 size-8" />
                            {query || kind !== ALL || category !== ALL ? "Aucun article ne correspond." : "Le catalogue est vide : ajoutez un article ou importez un CSV."}
                        </div>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Article</TableHead>
                                    <TableHead>Catégorie</TableHead>
                                    <TableHead>Prix</TableHead>
                                    <TableHead>Stock</TableHead>
                                    <TableHead />
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {items.map((item) => (
                                    <TableRow key={item.id} data-testid="catalog-item">
                                        <TableCell>
                                            <p className="font-medium">{item.name}</p>
                                            <p className="text-xs text-muted-foreground">
                                                {item.kind_label}
                                                {item.sku ? ` · ${item.sku}` : ""}
                                                {Object.keys(item.attributes).length > 0 &&
                                                    ` · ${Object.entries(item.attributes)
                                                        .slice(0, 3)
                                                        .map(([k, v]) => `${k} ${v}`)
                                                        .join(", ")}`}
                                            </p>
                                        </TableCell>
                                        <TableCell>{item.category ?? "—"}</TableCell>
                                        <TableCell className="whitespace-nowrap">{item.price_text ?? "Sur demande"}</TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2">
                                                <Input
                                                    aria-label={`Stock de ${item.name}`}
                                                    className="h-8 w-20"
                                                    inputMode="numeric"
                                                    placeholder="—"
                                                    defaultValue={item.stock ?? ""}
                                                    onBlur={async (e) => {
                                                        const value = e.target.value.trim();
                                                        const stock = value === "" ? null : Number(value);
                                                        if (stock === item.stock || (stock !== null && (!Number.isInteger(stock) || stock < 0))) return;
                                                        const response = await updateStockApiV1CatalogItemsItemIdStockPatch({ path: { item_id: item.id }, body: { stock } });
                                                        if (response.error) toast.error(detailFromError(response.error, "Stock non enregistré"));
                                                        else void load();
                                                    }}
                                                />
                                                {!item.available ? <Badge variant="outline">Indisponible</Badge> : !item.in_stock ? <Badge variant="destructive">Épuisé</Badge> : null}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <Button variant="ghost" size="icon" aria-label={`Modifier ${item.name}`} onClick={() => setEditing({ id: item.id, form: toForm(item) })}>
                                                <Pencil />
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                aria-label={`Supprimer ${item.name}`}
                                                onClick={async () => {
                                                    if (!window.confirm(`Supprimer « ${item.name} » du catalogue ?`)) return;
                                                    const response = await deleteItemApiV1CatalogItemsItemIdDelete({ path: { item_id: item.id } });
                                                    if (response.error) toast.error(detailFromError(response.error, "Suppression impossible"));
                                                    else void load();
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

                <PageSection title="Essayer comme l'agent" description="Ce que l'agent obtiendrait pour la demande d'un client.">
                    <div className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
                        <div className="space-y-1">
                            <Label htmlFor="preview-query">Le client cherche…</Label>
                            <Input id="preview-query" placeholder="villa piscine Cocody" value={preview.query} onChange={(e) => setPreview({ ...preview, query: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="preview-budget">Budget maximum</Label>
                            <Input id="preview-budget" inputMode="numeric" value={preview.budget} onChange={(e) => setPreview({ ...preview, budget: e.target.value })} />
                        </div>
                        <Button variant="outline" onClick={() => void runPreview()}>
                            <Sparkles /> Essayer
                        </Button>
                    </div>
                    {preview.result && (
                        <pre className="mt-3 whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-sm" data-testid="catalog-preview">
                            {preview.result}
                        </pre>
                    )}
                </PageSection>
            </div>

            <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
                <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>{editing?.id === null ? "Nouvel article" : "Modifier l\u2019article"}</DialogTitle>
                        <DialogDescription>Ce que l&apos;agent pourra annoncer : soyez précis sur le prix, l&apos;unité et les caractéristiques.</DialogDescription>
                    </DialogHeader>
                    {editing && (
                        <div className="grid gap-4 sm:grid-cols-2">
                            <div className="space-y-1 sm:col-span-2">
                                <Label htmlFor="item-name">Nom</Label>
                                <Input id="item-name" value={editing.form.name} onChange={(e) => set({ name: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label>Type</Label>
                                <Select value={editing.form.kind} onValueChange={(v) => set({ kind: v })}>
                                    <SelectTrigger aria-label="Type d'article">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {KINDS.map(([value, label]) => (
                                            <SelectItem key={value} value={value}>
                                                {label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="item-sku">Référence</Label>
                                <Input id="item-sku" value={editing.form.sku} onChange={(e) => set({ sku: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="item-category">Catégorie</Label>
                                <Input id="item-category" list="catalog-categories" value={editing.form.category} onChange={(e) => set({ category: e.target.value })} />
                                <datalist id="catalog-categories">
                                    {categories.map((c) => (
                                        <option key={c} value={c} />
                                    ))}
                                </datalist>
                            </div>
                            <div className="grid grid-cols-[1fr_5rem] gap-2">
                                <div className="space-y-1">
                                    <Label htmlFor="item-price">Prix</Label>
                                    <Input id="item-price" inputMode="decimal" placeholder="Sur demande" value={editing.form.price} onChange={(e) => set({ price: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="item-currency">Devise</Label>
                                    <Input id="item-currency" maxLength={3} value={editing.form.currency} onChange={(e) => set({ currency: e.target.value })} />
                                </div>
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="item-unit">Unité</Label>
                                <Input id="item-unit" placeholder="la nuit, le kg, par mois…" value={editing.form.unit} onChange={(e) => set({ unit: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="item-stock">Stock</Label>
                                <Input id="item-stock" inputMode="numeric" placeholder="Non suivi" value={editing.form.stock} onChange={(e) => set({ stock: e.target.value })} />
                            </div>
                            <div className="space-y-1 sm:col-span-2">
                                <Label htmlFor="item-description">Description</Label>
                                <Textarea id="item-description" rows={3} value={editing.form.description} onChange={(e) => set({ description: e.target.value })} />
                            </div>
                            <div className="space-y-1 sm:col-span-2">
                                <Label htmlFor="item-attributes">Caractéristiques (une par ligne, « clé : valeur »)</Label>
                                <Textarea id="item-attributes" rows={4} placeholder={"chambres: 4\nsurface: 180 m²\nvue: mer"} value={editing.form.attributes} onChange={(e) => set({ attributes: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="item-url">Lien (fiche, photos)</Label>
                                <Input id="item-url" placeholder="https://" value={editing.form.url} onChange={(e) => set({ url: e.target.value })} />
                            </div>
                            <div className="flex items-center gap-3 pt-6">
                                <Switch id="item-available" checked={editing.form.available} onCheckedChange={(available) => set({ available })} />
                                <Label htmlFor="item-available">Disponible</Label>
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditing(null)}>
                            Annuler
                        </Button>
                        <Button disabled={!editing?.form.name.trim()} onClick={() => void save()}>
                            Enregistrer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageLayout>
    );
}

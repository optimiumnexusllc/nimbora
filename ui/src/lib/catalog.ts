import type { CatalogItemIn } from "@/client/types.gen";

export type CatalogItem = {
    id: number;
    kind: string;
    kind_label: string;
    sku: string | null;
    name: string;
    description: string | null;
    category: string | null;
    price: number | null;
    price_text: string | null;
    currency: string;
    unit: string | null;
    stock: number | null;
    available: boolean;
    in_stock: boolean;
    attributes: Record<string, string | number | boolean>;
    tags: string[];
    url: string | null;
};

export const KINDS: [string, string][] = [
    ["product", "Produit"],
    ["property", "Bien immobilier"],
    ["room", "Chambre"],
    ["service", "Prestation"],
    ["vehicle", "Véhicule"],
    ["other", "Autre"],
];

export type CatalogForm = {
    kind: string;
    sku: string;
    name: string;
    description: string;
    category: string;
    price: string;
    currency: string;
    unit: string;
    stock: string;
    available: boolean;
    attributes: string; // « clé: valeur » per line
    url: string;
};
export const EMPTY_FORM: CatalogForm = { kind: "product", sku: "", name: "", description: "", category: "", price: "", currency: "XOF", unit: "", stock: "", available: true, attributes: "", url: "" };

export function toForm(item: CatalogItem): CatalogForm {
    return {
        kind: item.kind,
        sku: item.sku ?? "",
        name: item.name,
        description: item.description ?? "",
        category: item.category ?? "",
        price: item.price === null ? "" : String(item.price),
        currency: item.currency,
        unit: item.unit ?? "",
        stock: item.stock === null ? "" : String(item.stock),
        available: item.available,
        attributes: Object.entries(item.attributes)
            .map(([k, v]) => `${k}: ${v}`)
            .join("\n"),
        url: item.url ?? "",
    };
}

/** Form → API body; « clé: valeur » lines become characteristics. */
export function fromForm(form: CatalogForm): CatalogItemIn {
    const attributes: Record<string, string> = {};
    for (const line of form.attributes.split("\n")) {
        const at = line.indexOf(":");
        if (at > 0 && line.slice(at + 1).trim()) attributes[line.slice(0, at).trim()] = line.slice(at + 1).trim();
    }
    const price = form.price.replace(/[\s  ]/g, "").replace(",", ".");
    return {
        kind: form.kind as CatalogItemIn["kind"],
        sku: form.sku.trim() || null,
        name: form.name.trim(),
        description: form.description.trim() || null,
        category: form.category.trim() || null,
        price: price === "" ? null : price,
        currency: form.currency.trim().toUpperCase() || "XOF",
        unit: form.unit.trim() || null,
        stock: form.stock.trim() === "" ? null : Number(form.stock),
        available: form.available,
        attributes,
        tags: [],
        url: form.url.trim() || null,
    };
}


/** Save a text as a file in the browser. */
export function download(name: string, text: string, type = "text/csv;charset=utf-8") {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
}

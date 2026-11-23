import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fromForm, toForm } from "@/lib/catalog";

import CatalogPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    stock: vi.fn(),
    importFile: vi.fn(),
    exportCsv: vi.fn(),
    preview: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    listItemsApiV1CatalogItemsGet: mocks.list,
    createItemApiV1CatalogItemsPost: mocks.create,
    updateItemApiV1CatalogItemsItemIdPut: mocks.update,
    deleteItemApiV1CatalogItemsItemIdDelete: mocks.remove,
    updateStockApiV1CatalogItemsItemIdStockPatch: mocks.stock,
    importItemsApiV1CatalogImportPost: mocks.importFile,
    exportItemsApiV1CatalogExportCsvGet: mocks.exportCsv,
    agentPreviewApiV1CatalogAgentPreviewPost: mocks.preview,
}));

const villa = {
    id: 7,
    kind: "property",
    kind_label: "Bien immobilier",
    sku: "VIL-1",
    name: "Villa Riviera",
    description: null,
    category: "Ventes",
    price: 150000000,
    price_text: "150 000 000 F CFA",
    currency: "XOF",
    unit: null,
    stock: null,
    available: true,
    in_stock: true,
    attributes: { chambres: "4", quartier: "Riviera 3" },
    tags: [],
    url: null,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: { items: [villa], total: 1, categories: ["Ventes"] } });
    for (const m of [mocks.create, mocks.update, mocks.stock]) m.mockResolvedValue({ data: villa });
});

describe("catalog form", () => {
    it("turns characteristics lines into attributes and back", () => {
        const form = toForm(villa as never);
        expect(form.attributes).toBe("chambres: 4\nquartier: Riviera 3");
        const body = fromForm({ ...form, price: "150 000 000", stock: "", attributes: "chambres: 5\nvue : mer\nsans valeur:" });
        expect(body.price).toBe("150000000");
        expect(body.stock).toBeNull();
        expect(body.attributes).toEqual({ chambres: "5", vue: "mer" });
    });
});

describe("CatalogPage", () => {
    it("lists items and adds one", async () => {
        render(<CatalogPage />);
        const row = await screen.findByTestId("catalog-item");
        expect(row.textContent).toContain("Villa Riviera");
        expect(row.textContent).toContain("150 000 000 F CFA");
        expect(row.textContent).toContain("chambres 4");
        fireEvent.click(screen.getByRole("button", { name: /Ajouter/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Chambre Délux" } });
        fireEvent.change(screen.getByLabelText("Prix"), { target: { value: "85 000" } });
        fireEvent.change(screen.getByLabelText("Stock"), { target: { value: "3" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.create).toHaveBeenCalled();
        const body = mocks.create.mock.calls[0][0].body;
        expect(body).toMatchObject({ name: "Chambre Délux", price: "85000", stock: 3, currency: "XOF" });
    });

    it("searches as you type and changes a stock inline", async () => {
        render(<CatalogPage />);
        await screen.findByTestId("catalog-item");
        fireEvent.change(screen.getByLabelText("Rechercher dans le catalogue"), { target: { value: "piscine" } });
        await waitFor(() => expect(mocks.list.mock.calls.some((c) => c[0].query.q === "piscine")).toBe(true));
        const stock = screen.getByLabelText("Stock de Villa Riviera");
        fireEvent.change(stock, { target: { value: "2" } });
        await act(async () => {
            fireEvent.blur(stock);
        });
        expect(mocks.stock).toHaveBeenCalledWith({ path: { item_id: 7 }, body: { stock: 2 } });
    });

    it("imports a CSV and reports skipped lines", async () => {
        mocks.importFile.mockResolvedValue({ data: { created: 3, updated: 1, errors: [{ line: 5, message: "Prix illisible : abc" }] } });
        render(<CatalogPage />);
        await screen.findByTestId("catalog-item");
        const file = new File(["nom;prix\nVilla;100"], "catalogue.csv", { type: "text/csv" });
        await act(async () => {
            fireEvent.change(screen.getByTestId("catalog-file"), { target: { files: [file] } });
        });
        expect(mocks.importFile).toHaveBeenCalledWith({ body: { file } });
        expect(mocks.toast.success).toHaveBeenCalledWith("3 ajouté(s), 1 mis à jour");
        expect(mocks.toast.error).toHaveBeenCalledWith("Lignes ignorées : 5 (Prix illisible : abc)");
    });

    it("tries a search as the agent", async () => {
        mocks.preview.mockResolvedValue({ data: { items: [{ name: "Villa Riviera", price: "150 000 000 F CFA", availability: "disponible" }], total: 1 } });
        render(<CatalogPage />);
        await screen.findByTestId("catalog-item");
        fireEvent.change(screen.getByLabelText("Le client cherche…"), { target: { value: "villa" } });
        fireEvent.change(screen.getByLabelText("Budget maximum"), { target: { value: "200 000 000" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Essayer/ }));
        });
        expect(mocks.preview).toHaveBeenCalledWith({ body: { query: "villa", max_price: 200000000, available_only: true } });
        expect(screen.getByTestId("catalog-preview").textContent).toContain("Villa Riviera — 150 000 000 F CFA — disponible");
    });
});

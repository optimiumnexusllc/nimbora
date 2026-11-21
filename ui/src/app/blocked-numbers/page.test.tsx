import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import BlockedNumbersPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(), add: vi.fn(), remove: vi.fn(), importCsv: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    listBlockedNumbersApiV1BlockedNumbersGet: mocks.list,
    addBlockedNumberApiV1BlockedNumbersPost: mocks.add,
    removeBlockedNumberApiV1BlockedNumbersEntryIdDelete: mocks.remove,
    importBlockedNumbersApiV1BlockedNumbersImportPost: mocks.importCsv,
}));

const items = [
    { id: 1, number: "+2250707112233", direction: "inbound", reason: "Démarchage", source: "manual", expires_at: null, hits: 4, last_hit_at: "2026-11-21T09:00:00Z", created_at: "2026-11-20T09:00:00Z" },
    { id: 2, number: "+2250505050505", direction: "outbound", reason: "A demandé à ne plus être appelé (appel n°77)", source: "caller_request", expires_at: null, hits: 1, last_hit_at: null, created_at: "2026-11-21T08:00:00Z" },
];

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.list.mockResolvedValue({ data: { items, total: 2, stats: { total: 2, hits: 5, caller_requests: 1 } } });
    mocks.add.mockResolvedValue({ data: { ...items[0], id: 3, number: "+33612345678" } });
    mocks.remove.mockResolvedValue({ data: null });
    mocks.importCsv.mockResolvedValue({ data: { imported: 1, errors: [{ line: 2, value: "xx", error: "Numéro invalide : xx" }] } });
});

describe("BlockedNumbersPage", () => {
    it("shows the list with its origin and the calls it avoided", async () => {
        render(<BlockedNumbersPage />);
        const rows = await screen.findAllByTestId("blocked-row");
        expect(rows[0].textContent).toContain("Appels reçus");
        expect(rows[1].textContent).toContain("Demande du client");
        expect(rows[1].textContent).toContain("Appels émis");
        const stats = screen.getAllByTestId("blocked-stat").map((s) => s.textContent);
        expect(stats[0]).toContain("2");
        expect(stats[1]).toContain("1");
        expect(stats[2]).toContain("5");
    });

    it("blocks, imports and unblocks numbers", async () => {
        render(<BlockedNumbersPage />);
        await screen.findAllByTestId("blocked-row");
        fireEvent.change(screen.getByLabelText("Numéro"), { target: { value: "+33 6 12 34 56 78" } });
        selectOption(screen.getByRole("combobox", { name: "Sens" }), "Appels émis");
        fireEvent.change(screen.getByLabelText("Motif"), { target: { value: "Opposition" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /^Bloquer$/ }));
        });
        expect(mocks.add).toHaveBeenCalledWith({ body: { number: "+33 6 12 34 56 78", direction: "outbound", reason: "Opposition" } });

        const file = new File(["+33612345678;Opposition;sortant\nxx;;\n"], "liste.csv", { type: "text/csv" });
        Object.defineProperty(file, "text", { value: () => Promise.resolve("+33612345678;Opposition;sortant\nxx;;\n") });
        await act(async () => {
            fireEvent.change(screen.getByTestId("blocked-import-input"), { target: { files: [file] } });
        });
        await waitFor(() => expect(mocks.importCsv).toHaveBeenCalledWith({ body: { content: "+33612345678;Opposition;sortant\nxx;;\n" } }));
        expect((await screen.findByTestId("blocked-import-errors")).textContent).toContain("Ligne 2 (xx)");

        const row = screen.getAllByTestId("blocked-row")[0];
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: /Débloquer/ }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { entry_id: 1 } });
    });
});

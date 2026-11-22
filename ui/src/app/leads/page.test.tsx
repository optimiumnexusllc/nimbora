import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { leadFromForm, leadToForm, temperature } from "@/lib/leads";

import LeadsPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    move: vi.fn(),
    remove: vi.fn(),
    exportCsv: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    listLeadsApiV1LeadsGet: mocks.list,
    createLeadApiV1LeadsPost: mocks.create,
    updateLeadApiV1LeadsLeadIdPut: mocks.update,
    moveLeadApiV1LeadsLeadIdStagePost: mocks.move,
    deleteLeadApiV1LeadsLeadIdDelete: mocks.remove,
    exportLeadsApiV1LeadsExportCsvGet: mocks.exportCsv,
}));

const awa = {
    id: 1,
    name: "Awa Koné",
    phone: "+2250700112233",
    email: null,
    company: null,
    need: "Villa 4 chambres avec piscine",
    budget_min: null,
    budget_max: 150000000,
    budget_text: "jusqu'à 150 000 000 F CFA",
    currency: "XOF",
    timeline: "dans 3 mois",
    decision_maker: true,
    interests: ["Villa Riviera"],
    stage: "qualified",
    stage_label: "Qualifié",
    score: 95,
    source: "call",
    owner: null,
    notes: null,
    lost_reason: null,
    next_action: null,
    next_action_at: null,
    updated_at: null,
};
const pipeline = ["new", "qualified", "proposal", "negotiation", "won", "lost"].map((stage) => ({
    stage,
    label: stage,
    count: stage === "qualified" ? 1 : 0,
    budgets: stage === "qualified" ? [{ currency: "XOF", total: 150000000, text: "150 000 000 F CFA" }] : [],
}));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: { leads: [awa], pipeline } });
    for (const m of [mocks.create, mocks.update, mocks.move]) m.mockResolvedValue({ data: awa });
});

describe("leads helpers", () => {
    it("round-trips the form and rates the score", () => {
        const form = leadToForm(awa as never);
        expect(form.decision_maker).toBe("yes");
        const body = leadFromForm({ ...form, budget_max: "150 000 000", decision_maker: "" }, ["Villa Riviera"]);
        expect(body).toMatchObject({ budget_max: "150000000", decision_maker: null, interests: ["Villa Riviera"] });
        expect([temperature(95).label, temperature(50).label, temperature(10).label]).toEqual(["Chaud", "Tiède", "Froid"]);
    });
});

describe("LeadsPage", () => {
    it("shows the pipeline with each stage's count and budget", async () => {
        render(<LeadsPage />);
        const card = await screen.findByTestId("lead");
        const qualified = screen.getByTestId("stage-qualified");
        expect(within(qualified).getByTestId("lead")).toBe(card);
        expect(qualified.textContent).toContain("150 000 000 F CFA");
        expect(card.textContent).toContain("Chaud · 95");
        expect(card.textContent).toContain("Appel · dans 3 mois");
    });

    it("creates a lead from the sheet", async () => {
        render(<LeadsPage />);
        await screen.findByTestId("lead");
        fireEvent.click(screen.getByRole("button", { name: /Nouveau prospect/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Ibrahim Sanogo" } });
        fireEvent.change(screen.getByLabelText("Besoin"), { target: { value: "Bureaux au Plateau" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.create.mock.calls[0][0].body).toMatchObject({ name: "Ibrahim Sanogo", need: "Bureaux au Plateau", stage: "new" });
    });

    it("searches", async () => {
        render(<LeadsPage />);
        await screen.findByTestId("lead");
        fireEvent.change(screen.getByLabelText("Rechercher un prospect"), { target: { value: "awa" } });
        await vi.waitFor(() => expect(mocks.list.mock.calls.some((c) => c[0].query.q === "awa")).toBe(true));
    });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { destinationLabel, RoutingTab } from "./RoutingTab";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), simulate: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    readRoutingApiV1PbxRoutingGet: mocks.read,
    saveRoutingApiV1PbxRoutingPut: mocks.save,
    simulateRoutingApiV1PbxRoutingSimulatePost: mocks.simulate,
}));

const queues = [
    { id: 1, name: "Accueil", extensions: ["3000"], members: 2 },
    { id: 2, name: "Facturation", extensions: ["3001"], members: 1 },
];
const users = [
    { uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true },
    { uuid: "u-2", name: "Aya Bamba", extension: "1002", email: null, enabled: true },
];
const policy = {
    enabled: true,
    default_destination: "pbx-queue:1",
    vip_destination: "",
    usual_advisor: true,
    usual_advisor_days: 180,
    skills: [{ name: "Facturation", destination: "pbx-queue:2" }],
    languages: {},
    agents: {},
    when_unavailable: "queue",
    callback_delay_minutes: 15,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: policy });
    mocks.save.mockImplementation(async ({ body }) => ({ data: body }));
});

describe("RoutingTab", () => {
    it("gives agents skills and languages, then saves the policy", async () => {
        render(<RoutingTab queues={queues} users={users} />);
        await waitFor(() => expect(screen.getByTestId("routing-tab")).toBeTruthy());
        const skillButtons = screen.getAllByRole("button", { name: "Facturation" });
        fireEvent.click(skillButtons[1]); // Aya Bamba (1002)
        fireEvent.change(screen.getByLabelText("Langues du poste 1002"), { target: { value: "fr, EN" } });
        fireEvent.click(screen.getByRole("button", { name: /Ajouter une compétence/ }));
        fireEvent.change(screen.getByLabelText("Compétence 2"), { target: { value: "Ventes" } });
        fireEvent.click(screen.getByRole("button", { name: /Enregistrer la politique/ }));
        await waitFor(() => expect(mocks.save).toHaveBeenCalled());
        const body = mocks.save.mock.calls[0][0].body;
        expect(body.agents["1002"]).toEqual({ skills: ["Facturation"], languages: ["fr", "en"] });
        expect(body.skills.map((s: { name: string }) => s.name)).toEqual(["Facturation", "Ventes"]);
    });

    it("simulates where a customer would go, with the reasons", async () => {
        mocks.simulate.mockResolvedValue({
            data: {
                destination: "pbx-extension:1002",
                reason: "usual_advisor",
                explanation: "Conseiller habituel disponible : Aya Bamba",
                steps: ["Client non VIP", "→ Conseiller habituel disponible : Aya Bamba"],
            },
        });
        render(<RoutingTab queues={queues} users={users} />);
        await waitFor(() => expect(screen.getByTestId("routing-simulator")).toBeTruthy());
        fireEvent.change(screen.getByLabelText("Numéro du client"), { target: { value: "+2250102030405" } });
        fireEvent.change(screen.getByLabelText("Demande (compétence)"), { target: { value: "facturation" } });
        fireEvent.click(screen.getByRole("button", { name: /Simuler/ }));
        await waitFor(() => expect(screen.getByTestId("routing-decision")).toBeTruthy());
        const result = screen.getByTestId("routing-decision").textContent ?? "";
        expect(result).toContain("Conseiller habituel");
        expect(result).toContain("Poste 1002 · Aya Bamba");
        expect(result).toContain("Client non VIP");
        expect(mocks.simulate.mock.calls[0][0].body).toEqual({
            caller_number: "+2250102030405",
            language: "fr",
            skill: "facturation",
        });
    });

    it("labels destinations with queue and extension names", () => {
        expect(destinationLabel("pbx-queue:2", queues, users)).toBe("File Facturation");
        expect(destinationLabel("pbx-extension:1001", queues, users)).toBe("Poste 1001 · Koffi Yao");
        expect(destinationLabel(null, queues, users)).toBe("—");
    });
});

describe("RoutingTab when nobody is free", () => {
    it("says what the policy would do", async () => {
        mocks.read.mockResolvedValue({ data: { ...policy, when_unavailable: "callback" } });
        mocks.simulate.mockResolvedValue({
            data: {
                destination: null,
                reason: "unavailable",
                explanation: "Aucun conseiller n'est disponible pour le moment.",
                steps: ["Personne de libre pour « Facturation »"],
                when_unavailable: "callback",
            },
        });
        render(<RoutingTab queues={queues} users={users} />);
        await waitFor(() => expect(screen.getByTestId("routing-simulator")).toBeTruthy());
        fireEvent.click(screen.getByRole("button", { name: /Simuler/ }));
        await waitFor(() => expect(screen.getByTestId("routing-decision")).toBeTruthy());
        const result = screen.getByTestId("routing-decision").textContent ?? "";
        expect(result).toContain("Personne de libre");
        expect(result).toContain("planifierait un rappel (dans 15 min)");
    });
});

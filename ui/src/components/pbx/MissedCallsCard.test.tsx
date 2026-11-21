import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { MissedCallsCard } from "./MissedCallsCard";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    readMissedCallsApiV1PbxMissedCallsGet: mocks.read,
    saveMissedCallsApiV1PbxMissedCallsPut: mocks.save,
}));

const workflows = [
    { id: 4, name: "Accueil Ivoire Immo" },
    { id: 9, name: "Rappels clients" },
] as never;

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({
        data: {
            policy: { enabled: false, workflow_id: null, delay_minutes: 5, scope: "queues", within_hours: true },
            recent: [
                {
                    id: 1,
                    phone: "+2250102030405",
                    customer_name: "Ibrahim Touré",
                    reason: "Appel manqué le 21/11 à 10:42 (la file Ventes)",
                    status: "done",
                    outcome: "Rendez-vous pris samedi 10 h",
                    attempts: 1,
                    scheduled_at: "2026-11-21T10:47:00Z",
                },
                {
                    id: 2,
                    phone: "+2250707070707",
                    customer_name: null,
                    reason: "Appel manqué",
                    status: "canceled",
                    outcome: "Le client a été servi entre-temps : rappel annulé",
                    attempts: 0,
                    scheduled_at: null,
                },
            ],
        },
    });
    mocks.save.mockResolvedValue({ data: { policy: {} } });
});

describe("MissedCallsCard", () => {
    it("shows the latest automatic callbacks and saves the policy", async () => {
        render(<MissedCallsCard workflows={workflows} />);
        await waitFor(() => expect(screen.getByTestId("missed-callbacks")).toBeTruthy());
        expect(screen.getByText("Rendez-vous pris samedi 10 h")).toBeTruthy();
        expect(screen.getByText("Annulé")).toBeTruthy();

        fireEvent.click(screen.getByRole("switch", { name: "Rappeler automatiquement les appels manqués" }));
        await selectOption(screen.getByLabelText("Agent IA qui rappelle"), "Rappels clients");
        fireEvent.click(screen.getByRole("radio", { name: "Tous les appels manqués" }));
        fireEvent.change(screen.getByLabelText("Rappeler après (minutes)"), { target: { value: "15" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.save).toHaveBeenCalledWith({
            body: { enabled: true, workflow_id: 9, delay_minutes: 15, scope: "all", within_hours: true },
        });
    });
});

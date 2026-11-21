import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CustomersPage from "./page";

const mocks = vi.hoisted(() => ({
    readSecret: vi.fn(),
    rotate: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    readIdentitySecretApiV1CustomersIdentityGet: mocks.readSecret,
    rotateIdentityApiV1CustomersIdentityRotatePost: mocks.rotate,
}));
vi.mock("@/lib/enterpriseApi", () => ({
    enterpriseApi: {
        listCustomers: mocks.list,
        getCustomer: mocks.get,
        updateCustomer: vi.fn(),
        forgetCustomer: vi.fn(),
        setMemoryEnabled: vi.fn(),
        createCustomer: vi.fn(),
    },
}));

const customer = {
    id: 3, phone: "+2250700112233", name: "Awa Koné", notes: null, tags: [], attributes: {},
    total_calls: 3, first_seen_at: "2026-11-01T09:00:00Z", last_seen_at: "2026-11-20T10:00:00Z",
    last_summary: "Cherche un 3 pièces à Cocody", last_sentiment: "positive",
};
const interaction = (id: number, channel: string, summary: string) => ({
    id, workflow_run_id: id, direction: "inbound", agent_name: "Ivoire Immo", summary, sentiment: null,
    outcome: null, transferred_to_queue: null, duration_seconds: 120, channel, created_at: "2026-11-20T10:00:00Z",
});

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.list.mockResolvedValue({ customers: [customer], total: 1, memory_enabled: true });
    mocks.get.mockResolvedValue({
        ...customer,
        interactions: [
            interaction(1, "whatsapp", "Budget 250 000 FCFA"),
            interaction(2, "phone", "Visite samedi"),
            interaction(3, "web", "Question sur les frais"),
        ],
    });
    mocks.readSecret.mockResolvedValue({ data: { secret: "a".repeat(64) } });
    mocks.rotate.mockResolvedValue({ data: { secret: "b".repeat(64) } });
});

describe("customers page", () => {
    it("labels each past exchange with its channel", async () => {
        render(<CustomersPage />);
        await waitFor(() => expect(screen.getByText("Awa Koné")).toBeTruthy());
        fireEvent.click(screen.getByText("Awa Koné"));
        await waitFor(() => expect(screen.getByText("Budget 250 000 FCFA")).toBeTruthy());
        expect(screen.getByText("WhatsApp")).toBeTruthy();
        expect(screen.getByText("Téléphone")).toBeTruthy();
        expect(screen.getByText("Chat web")).toBeTruthy();
    });

    it("shows and rotates the web identity secret", async () => {
        render(<CustomersPage />);
        fireEvent.click(screen.getByRole("button", { name: /clients identifiés/ }));
        await waitFor(() =>
            expect((screen.getByTestId("identity-secret") as HTMLInputElement).value).toBe("a".repeat(64)),
        );
        expect(screen.getByText(/createHmac/)).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Renouveler le secret/ }));
        });
        expect(mocks.rotate).toHaveBeenCalled();
        expect((screen.getByTestId("identity-secret") as HTMLInputElement).value).toBe("b".repeat(64));
    });
});

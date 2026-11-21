import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConversationsPage from "./page";

const mocks = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("@/client/sdk.gen", () => ({
    listConversationsApiV1WhatsappConversationsGet: mocks.list,
    getConversationApiV1WhatsappConversationsConversationIdGet: mocks.get,
}));

const base = {
    business_number: "+2250700000001", workflow_id: 4, workflow_run_id: 77, message_count: 2,
    last_outbound_at: null, created_at: "2026-11-20T10:00:00Z",
};
const awa = { ...base, id: 1, customer_wa_id: "2250700112233", customer_name: "Awa", status: "open", last_inbound_at: "2026-11-20T10:05:00Z" };
const yao = { ...base, id: 2, customer_wa_id: "2250500998877", customer_name: null, status: "closed", last_inbound_at: "2026-11-19T08:00:00Z" };

beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: [awa, yao] });
    mocks.get.mockImplementation(async ({ path }) => ({
        data: {
            ...(path.conversation_id === 1 ? awa : yao),
            messages: path.conversation_id === 1
                ? [
                    { role: "agent", text: "Bonjour, ici Ivoire Immo !", at: null },
                    { role: "customer", text: "Je cherche un 3 pièces à Cocody", at: "2026-11-20T10:05:00Z" },
                ]
                : [{ role: "customer", text: "Merci, à demain", at: null }],
        },
    }));
});

describe("conversations page", () => {
    it("opens the latest conversation and shows the WhatsApp transcript", async () => {
        render(<ConversationsPage />);
        await waitFor(() => expect(screen.getByText("Je cherche un 3 pièces à Cocody")).toBeTruthy());
        expect(screen.getAllByTestId("conversation-row")).toHaveLength(2);
        expect(screen.getByText("Bonjour, ici Ivoire Immo !")).toBeTruthy();
        expect(screen.getByRole("link", { name: /Exécution/ }).getAttribute("href")).toBe("/workflow/4/run/77");
        expect(mocks.list).toHaveBeenCalledWith({ query: { status: "all" } });
    });

    it("switches conversation and filters by status", async () => {
        render(<ConversationsPage />);
        await waitFor(() => expect(screen.getAllByTestId("conversation-row")).toHaveLength(2));
        fireEvent.click(screen.getAllByTestId("conversation-row")[1]);
        await waitFor(() => expect(screen.getByText("Merci, à demain")).toBeTruthy());
        expect(screen.getAllByText("+2250500998877").length).toBeGreaterThan(0);
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Terminées/ }));
        await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ query: { status: "closed" } }));
    });

    it("explains how to start when there is no conversation", async () => {
        mocks.list.mockResolvedValue({ data: [] });
        render(<ConversationsPage />);
        await waitFor(() => expect(screen.getByText("Aucune conversation WhatsApp.")).toBeTruthy());
        expect(mocks.get).not.toHaveBeenCalled();
    });

    it("shows API errors", async () => {
        mocks.list.mockResolvedValue({ error: { detail: "No organization selected" } });
        render(<ConversationsPage />);
        await waitFor(() => expect(screen.getByText("No organization selected")).toBeTruthy());
    });
});

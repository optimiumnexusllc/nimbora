import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SupervisionPage from "./page";

const mocks = vi.hoisted(() => ({
    snapshot: vi.fn(),
    events: vi.fn(),
    action: vi.fn(),
    spy: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    snapshotApiV1SupervisionGet: mocks.snapshot,
    spyApiV1SupervisionSpyPost: mocks.spy,
    callEventsApiV1SupervisionCallsRunIdEventsGet: mocks.events,
    callActionApiV1SupervisionCallsRunIdActionsPost: mocks.action,
}));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.snapshot.mockResolvedValue({
        data: {
            ai_calls: [
                {
                    run_id: 42,
                    agent_name: "Accueil",
                    caller: "+22790123456",
                    state: "caller_speaking",
                    duration_seconds: 75,
                    last_caller_text: "Je veux résilier",
                    language: "fr",
                },
            ],
            agents: [
                { id: 7, display_name: "Ali", extension: "2002", status: "on_call", call: { with_number: "+336", with_name: "", seconds: 30 } },
                { id: 8, display_name: "Awa", extension: "2003", status: "paused", presence_reason: "Déjeuner" },
            ],
            queues: [
                { slug: "support", name: "Support", waiting: 2, longest_wait_seconds: 95, max_wait_seconds: 120, in_conversation: 1, available_agents: 0 },
            ],
            waiting_callers: [],
            kpis: { ai_calls: 1, human_calls: 1, waiting: 2, longest_wait_seconds: 95, agents_available: 0, agents_on_call: 1, agents_paused: 1, callbacks_pending: 3 },
            telephony: "ok",
            contact_center_enabled: true,
            my_seat: { id: 1, is_supervisor: true, presence: "available" },
        },
    });
    mocks.events.mockResolvedValue({
        data: { live: true, events: [{ seq: 1, kind: "caller", text: "Je veux résilier", at: 1 }] },
    });
    mocks.action.mockResolvedValue({ data: { status: "sent" } });
    mocks.spy.mockResolvedValue({ data: { status: "ringing" } });
});

describe("supervision console", () => {
    it("shows live AI calls, queues and agents, and lets a supervisor listen in", async () => {
        render(<SupervisionPage />);
        await waitFor(() => expect(screen.getByTestId("ai-call-card")).toBeTruthy());
        expect(screen.getByText("Déjeuner")).toBeTruthy();
        expect(screen.getByText("1:35")).toBeTruthy(); // longest wait in the queue table
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Écouter/ }));
        });
        expect(mocks.spy).toHaveBeenCalledWith({ body: { agent_id: 7, mode: "listen" } });
    });

    it("opens a call, follows the feed and whispers an instruction to the AI", async () => {
        render(<SupervisionPage />);
        await waitFor(() => expect(screen.getByTestId("ai-call-card")).toBeTruthy());
        fireEvent.click(screen.getByTestId("ai-call-card"));
        await waitFor(() => expect(screen.getByTestId("live-feed").textContent).toContain("Je veux résilier"));
        fireEvent.change(screen.getByPlaceholderText(/geste commercial/), {
            target: { value: "Propose un geste commercial de 10 %" },
        });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Souffler/ }));
        });
        expect(mocks.action).toHaveBeenCalledWith({
            path: { run_id: 42 },
            body: { action: "instruct", text: "Propose un geste commercial de 10 %", queue_slug: null },
        });
    });
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ActivityPage from "./page";

const mocks = vi.hoisted(() => ({
    summary: vi.fn(),
    appointments: vi.fn(),
    cancel: vi.fn(),
    messages: vi.fn(),
    tickets: vi.fn(),
    update: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    summaryApiV1ActionsSummaryGet: mocks.summary,
    listAppointmentsApiV1ActionsAppointmentsGet: mocks.appointments,
    cancelAppointmentApiV1ActionsAppointmentsAppointmentIdCancelPost: mocks.cancel,
    listMessagesApiV1ActionsMessagesGet: mocks.messages,
    listTicketsApiV1ActionsTicketsGet: mocks.tickets,
    updateTicketApiV1ActionsTicketsTicketIdPatch: mocks.update,
}));

const ticket = {
    id: 9, number: 1042, provider: "nimbora", subject: "Box en panne", description: "Plus d'internet",
    category: "technique", priority: "high", status: "open", customer_name: "Awa", phone: "+336",
    email: null, resolution: null, external_url: null, created_at: "2026-11-20T10:00:00Z",
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.summary.mockResolvedValue({ data: { upcoming_appointments: 1, messages_today: 0, open_tickets: 1 } });
    mocks.appointments.mockResolvedValue({
        data: [{ id: 5, calendar_key: "c", calendar_name: "Agence", provider: "nimbora", start_at: "2026-11-24T09:00:00Z",
                 end_at: "2026-11-24T09:30:00Z", customer_name: "Moussa", phone: "+227", email: null, reason: "Ouverture de compte",
                 status: "booked" }],
    });
    mocks.cancel.mockResolvedValue({ data: {} });
    mocks.messages.mockResolvedValue({ data: [] });
    mocks.tickets.mockResolvedValue({ data: [ticket] });
    mocks.update.mockImplementation(async ({ body }) => ({ data: { ...ticket, ...body } }));
});

describe("activity page", () => {
    it("lists appointments and cancels one", async () => {
        render(<ActivityPage />);
        await waitFor(() => expect(screen.getByTestId("appointment-row")).toBeTruthy());
        expect(screen.getByText("Moussa")).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Annuler/ }));
        });
        expect(mocks.cancel).toHaveBeenCalledWith({ path: { appointment_id: 5 } });
    });

    it("resolves a ticket with a resolution the AI will read out", async () => {
        render(<ActivityPage />);
        await waitFor(() => expect(screen.getByRole("tab", { name: /Tickets/ })).toBeTruthy());
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Tickets/ }));
        fireEvent.click(screen.getByRole("tab", { name: /Tickets/ }));
        await waitFor(() => expect(screen.getByTestId("ticket-row")).toBeTruthy());
        fireEvent.click(screen.getByTestId("ticket-row"));
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "Box remplacée le 21/11" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Marquer résolu" }));
        });
        expect(mocks.update).toHaveBeenCalledWith({
            path: { ticket_id: 9 },
            body: { resolution: "Box remplacée le 21/11", status: "solved" },
        });
    });
});

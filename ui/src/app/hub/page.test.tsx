import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { changeText, shortDay } from "@/lib/businessHub";

import BusinessHubPage from "./page";

const mocks = vi.hoisted(() => ({ read: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({ readBusinessHubApiV1BusinessHubGet: mocks.read }));

const kpi = (value: number, previous: number, change: number | null, extra = {}) => ({ value, previous, change, ...extra });
const hub = {
    period: "30d",
    timezone: "Africa/Abidjan",
    kpis: {
        conversations: kpi(6, 4, 50),
        ai_calls: kpi(3, 1, 200, { inbound: 2, outbound: 1, minutes: 6 }),
        human_calls: kpi(1, 0, null, { minutes: 5 }),
        appointments: kpi(1, 1, 0, { upcoming: 1, canceled: 0 }),
        leads: kpi(2, 4, -50, { qualified: 1, won: 1, lost: 0, conversion: 50 }),
        customers: kpi(0, 0, null),
    },
    channels: [
        { channel: "phone", label: "Téléphone", count: 4, previous: 2, share: 66.7 },
        { channel: "whatsapp", label: "WhatsApp", count: 1, previous: 1, share: 16.7 },
        { channel: "web", label: "Web", count: 1, previous: 1, share: 16.7 },
    ],
    actions: { handoffs: 1, handoffs_answered: 1, handoff_rate: 33.3, messages_sent: 2, tickets_created: 1, tickets_open: 1, callbacks_created: 0, callbacks_done: 0, whatsapp_messages: 6 },
    pipeline: [{ currency: "XOF", open_leads: 1, budget: 50000000, text: "50 000 000 F CFA" }],
    daily: [{ day: "2026-11-21", phone_ai: 3, phone_human: 1, whatsapp: 0, web: 0, appointments: 1, leads: 1 }],
};

// jsdom has no ResizeObserver (Recharts' responsive container needs one).
globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
} as unknown as typeof ResizeObserver;

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: hub });
});

describe("business hub helpers", () => {
    it("writes changes and days in French", () => {
        expect(changeText(kpi(3, 1, 200)).text).toBe("+200 %");
        expect(changeText(kpi(2, 4, -50))).toEqual({ text: "−50 %", tone: "down" });
        expect(changeText(kpi(1, 0, null)).text).toBe("nouveau");
        expect(shortDay("2026-11-21")).toBe("21 nov.");
    });
});

describe("BusinessHubPage", () => {
    it("shows the key figures, channels, actions and pipeline", async () => {
        render(<BusinessHubPage />);
        const tiles = await screen.findAllByTestId("kpi");
        expect(tiles).toHaveLength(6);
        expect(tiles[1].textContent).toContain("2 entrants · 1 sortants · 6 min");
        expect(tiles[1].textContent).toContain("+200 %");
        expect(tiles[4].textContent).toContain("1 gagnés (50 %)");
        expect(screen.getByTestId("channels").textContent).toContain("Téléphone4 · 66,7 %");
        expect(screen.getByTestId("actions").textContent).toContain("1 (33,3 % des appels IA)");
        expect(screen.getByTestId("pipeline-value").textContent).toContain("50 000 000 F CFA");
    });

    it("offers the activity as a table, and changes period", async () => {
        render(<BusinessHubPage />);
        await screen.findAllByTestId("kpi");
        fireEvent.click(screen.getByRole("button", { name: /Tableau/ }));
        const table = screen.getByTestId("daily-table");
        expect(table.textContent).toContain("21 nov.");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "7 jours" }));
        });
        expect(mocks.read).toHaveBeenLastCalledWith({ query: { period: "7d" } });
    });
});

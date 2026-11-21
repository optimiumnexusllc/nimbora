import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SupervisionWallPage from "./page";

const mocks = vi.hoisted(() => ({ snapshot: vi.fn(), live: vi.fn() }));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ loading: false, user: { id: "u" }, getAccessToken: async () => "jwt" }),
}));
vi.mock("@/client/sdk.gen", () => ({
    snapshotApiV1SupervisionGet: mocks.snapshot,
    readLiveApiV1PbxSupervisionLiveGet: mocks.live,
}));

beforeEach(() => {
    vi.stubGlobal("WebSocket", undefined);
    mocks.snapshot.mockResolvedValue({ data: { ai_calls: [{ run_id: 1 }, { run_id: 2 }], kpis: {} } });
    mocks.live.mockResolvedValue({
        data: {
            queues: [
                { id: 1, name: "Ventes", number: "3001", live: true, waiting: 2, longest_wait_seconds: 150, callers: [],
                  agents_available: 0, agents_on_call: 1, agents_paused: 0, agents_logged: 1, members: 1, sla_seconds: 20 },
                { id: 2, name: "Gestion locative", number: "3002", live: true, waiting: 0, longest_wait_seconds: 0, callers: [],
                  agents_available: 2, agents_on_call: 0, agents_paused: 0, agents_logged: 2, members: 2, sla_seconds: 20 },
            ],
            agents: [
                { id: 7, number: "1001", name: "Koffi Yao", user_uuid: "u-1", extension: "1001", state: "on_call", paused_reason: null,
                  call: { call_id: "c", seconds: 65 } },
                { id: 8, number: "1003", name: "Mariam Traoré", user_uuid: "u-3", extension: "1003", state: "available", paused_reason: null, call: null },
            ],
            calls: [],
            kpis: { calls: 1, waiting: 2, longest_wait_seconds: 150, agents_available: 2, agents_on_call: 1, agents_paused: 0, agents_logged_out: 0 },
            listening: { enabled: false, modes: [], supervisors: [] },
            errors: {},
            alerts: [
                { key: "no_agent:1", kind: "no_agent", level: "critical", queue_id: 1, queue_name: "Ventes", value: 2,
                  message: "Ventes : 2 appelants en attente et aucun conseiller disponible" },
            ],
        },
    });
});

describe("supervision wall", () => {
    it("shows the floor at a glance: totals, queues, agents and alerts", async () => {
        render(<SupervisionWallPage />);
        await waitFor(() => expect(screen.getAllByTestId("wall-queue")).toHaveLength(2));
        expect(screen.getByTestId("wall-waiting").textContent).toContain("2");
        expect(screen.getByTestId("wall-longest").textContent).toContain("2:30");
        expect(screen.getByTestId("wall-ai").textContent).toContain("2");
        expect(screen.getByRole("alert").textContent).toContain("aucun conseiller disponible");
        const ventes = screen.getAllByTestId("wall-queue")[0];
        expect(ventes.className).toContain("border-red-500");
        expect(ventes.textContent).toContain("0 disponible");
        expect(screen.getAllByTestId("wall-agent").map((a) => a.textContent)).toEqual(["Koffi Yao1:05", "Mariam Traoré"]);
    });

    it("says when no PBX is connected", async () => {
        mocks.live.mockResolvedValue({ error: { detail: "Aucun PBX connecté" }, response: { status: 404 } });
        render(<SupervisionWallPage />);
        expect(await screen.findByText("Aucun PBX connecté.")).toBeTruthy();
    });
});

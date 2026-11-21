import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import PbxPage from "./page";

const mocks = vi.hoisted(() => ({
    read: vi.fn(),
    save: vi.fn(),
    test: vi.fn(),
    inventory: vi.fn(),
    route: vi.fn(),
    unroute: vi.fn(),
    branding: vi.fn(),
    events: vi.fn(),
    hangup: vi.fn(),
    agent: vi.fn(),
    logs: vi.fn(),
    configs: vi.fn(),
    workflows: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    readConnectionApiV1PbxConnectionGet: mocks.read,
    saveConnectionApiV1PbxConnectionPut: mocks.save,
    testConnectionApiV1PbxConnectionTestPost: mocks.test,
    readInventoryApiV1PbxInventoryGet: mocks.inventory,
    routeNumberApiV1PbxRoutesPost: mocks.route,
    unrouteNumberApiV1PbxRoutesNumberDelete: mocks.unroute,
    applyBrandingApiV1PbxBrandingApplyPost: mocks.branding,
    connectEventsApiV1PbxEventsConnectPost: mocks.events,
    hangupCallApiV1PbxCallsCallIdHangupPost: mocks.hangup,
    agentActionApiV1PbxAgentsAgentNumberActionPost: mocks.agent,
    callLogsApiV1PbxCallLogsGet: mocks.logs,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet: mocks.configs,
    getWorkflowsSummaryApiV1WorkflowSummaryGet: mocks.workflows,
}));

const brand = { name: "NIMBORA", pbx_name: "NIMBORA Voice", sip_user_agent: "NIMBORA-Voice" };
const connected = {
    configured: true, brand, name: "Siège", base_url: "https://pbx.ivoire-immo.ci", username: "nimbora-integration",
    password: "••••••••", tenant_uuid: "t-1", verify_tls: true, ari_configuration_id: 3, incall_context: null,
    status: "ok", last_error: null, engine_version: "26.09", last_checked_at: "2026-11-21T09:00:00Z",
    branding_applied_at: null, events_connected: false,
};
const inventory = {
    users: [{ uuid: "u-1", name: "Koffi Yao", extension: "1001", email: "koffi@ivoire-immo.ci", enabled: true }],
    queues: [{ id: 1, name: "Ventes", extensions: ["3001"], members: 2 }],
    agents: [{ id: 7, number: "1001", name: "Koffi Yao", logged: true, paused: false, paused_reason: null, extension: "1001" }],
    numbers: [
        { number: "+22527000000", incall_id: 5, description: "Standard", destination: "File d'attente", ai_workflow_id: null, ai_workflow_name: null },
        { number: "+22527000099", incall_id: 9, description: null, destination: "Agent IA", ai_workflow_id: 4, ai_workflow_name: "Accueil" },
    ],
    calls: [{ call_id: "c-1", caller: "+2250700112233", caller_name: "Awa", peer: "1001", peer_name: "Koffi Yao", status: "Up", direction: "inbound", since: new Date().toISOString(), on_hold: false }],
    errors: {},
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.read.mockResolvedValue({ data: connected });
    mocks.inventory.mockResolvedValue({ data: inventory });
    mocks.configs.mockResolvedValue({ data: { configurations: [{ id: 3, name: "PBX (ARI)", provider: "ari" }, { id: 4, name: "Twilio", provider: "twilio" }] } });
    mocks.workflows.mockResolvedValue({ data: [{ id: 4, name: "Accueil" }, { id: 6, name: "Recouvrement" }] });
    for (const m of [mocks.route, mocks.unroute, mocks.branding, mocks.events, mocks.hangup, mocks.agent]) m.mockResolvedValue({ data: {} });
    mocks.logs.mockResolvedValue({ data: [{ id: 1, start: "2026-11-21T08:00:00Z", answered: false, duration: 0, direction: "inbound", source_name: "Awa", source: "+225", destination_name: "Koffi Yao", destination: "1001" }] });
});

describe("pbx page", () => {
    it("guides the first connection and only offers ARI configurations", async () => {
        mocks.read.mockResolvedValueOnce({ data: { configured: false, brand } });
        mocks.save.mockResolvedValue({ data: connected });
        render(<PbxPage />);
        expect(await screen.findByText("Connectez votre PBX")).toBeTruthy();
        expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("NIMBORA Voice");
        fireEvent.click(screen.getByRole("button", { name: /Connecter le PBX/ }));
        fireEvent.change(screen.getByLabelText("Adresse du PBX"), { target: { value: "https://pbx.ivoire-immo.ci" } });
        fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "s3cret" } });
        fireEvent.change(screen.getByLabelText("Tenant de l'entreprise"), { target: { value: "t-1" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer et tester/ }));
        });
        expect(mocks.save.mock.calls[0][0].body).toMatchObject({ base_url: "https://pbx.ivoire-immo.ci", username: "nimbora-integration", password: "s3cret", tenant_uuid: "t-1", incall_context: null });
        await waitFor(() => expect(screen.getByTestId("pbx-status").textContent).toContain("Connecté"));
        expect(mocks.toast.success).toHaveBeenCalledWith("Connecté à NIMBORA Voice");
    });

    it("shows live calls and agents and acts on them", async () => {
        render(<PbxPage />);
        expect(await screen.findByTestId("pbx-call")).toBeTruthy();
        expect(screen.getByTestId("pbx-status").textContent).toContain("version 26.09");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Raccrocher/ }));
        });
        expect(mocks.hangup).toHaveBeenCalledWith({ path: { call_id: "c-1" } });
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Agents/ }));
        const agent = await screen.findByTestId("pbx-agent");
        expect(agent.textContent).toContain("Disponible");
        await act(async () => {
            fireEvent.click(within(agent).getByRole("button", { name: /Pause/ }));
        });
        expect(mocks.agent).toHaveBeenCalledWith({ path: { agent_number: "1001", action: "pause" }, body: { reason: "Superviseur" } });
    });

    it("routes a number to an AI agent and removes an AI route", async () => {
        render(<PbxPage />);
        await screen.findByTestId("pbx-call");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Numéros/ }));
        const rows = await screen.findAllByTestId("pbx-number");
        expect(rows[0].textContent).toContain("File d'attente");
        expect(rows[1].textContent).toContain("Agent IA « Accueil »");
        expect(within(rows[0]).queryByRole("button", { name: /Retirer/ })).toBeNull();
        await act(async () => {
            fireEvent.click(within(rows[1]).getByRole("button", { name: /Retirer/ }));
        });
        expect(mocks.unroute).toHaveBeenCalledWith({ path: { number: "+22527000099" } });

        fireEvent.click(screen.getByRole("button", { name: /Router un numéro vers un agent IA/ }));
        fireEvent.change(await screen.findByLabelText("Numéro"), { target: { value: "+22527000100" } });
        selectOption(screen.getByRole("combobox", { name: "Agent IA" }), "Recouvrement");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /^Router$/ }));
        });
        expect(mocks.route).toHaveBeenCalledWith({ body: { number: "+22527000100", workflow_id: 6 } });
    });

    it("applies the brand, subscribes to events and shows partial outages", async () => {
        mocks.inventory.mockResolvedValue({ data: { ...inventory, calls: [], errors: { calls: "PBX injoignable : ConnectTimeout" } } });
        render(<PbxPage />);
        expect(await screen.findByText(/Indisponible pour le moment : PBX injoignable/)).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Appliquer la marque/ }));
        });
        expect(mocks.toast.success).toHaveBeenCalledWith("Marque appliquée : NIMBORA-Voice");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Recevoir les événements/ }));
        });
        expect(mocks.events).toHaveBeenCalled();
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Journal/ }));
        expect(await screen.findByText(/Manqué/)).toBeTruthy();
    });
});

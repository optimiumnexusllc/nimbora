import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import PbxPage from "./page";

const mocks = vi.hoisted(() => ({
    read: vi.fn(),
    save: vi.fn(),
    test: vi.fn(),
    inventory: vi.fn(),
    setNumber: vi.fn(),
    removeNumber: vi.fn(),
    menus: vi.fn(),
    voicemails: vi.fn(),
    trunks: vi.fn(),
    routes: vi.fn(),
    aiOutbound: vi.fn(),
    groups: vi.fn(),
    conferences: vi.fn(),
    callSettings: vi.fn(),
    restrictions: vi.fn(),
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
    setNumberDestinationApiV1PbxNumbersPut: mocks.setNumber,
    removeNumberApiV1PbxNumbersNumberDelete: mocks.removeNumber,
    listMenusApiV1PbxMenusGet: mocks.menus,
    listVoicemailsApiV1PbxVoicemailsGet: mocks.voicemails,
    listTrunksApiV1PbxTrunksGet: mocks.trunks,
    listOutboundRoutesApiV1PbxOutboundRoutesGet: mocks.routes,
    readAiOutboundApiV1PbxAiOutboundGet: mocks.aiOutbound,
    listGroupsApiV1PbxGroupsGet: mocks.groups,
    listConferencesApiV1PbxConferencesGet: mocks.conferences,
    readCallSettingsApiV1PbxExtensionsUserIdCallSettingsGet: mocks.callSettings,
    listRestrictionsApiV1PbxRestrictionsGet: mocks.restrictions,
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
    users: [{ id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: "koffi@ivoire-immo.ci", enabled: true }],
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
    mocks.menus.mockResolvedValue({
        data: [
            {
                id: 2, name: "Accueil", pbx_ivr_id: 31, published_at: "2026-11-21T09:00:00Z", up_to_date: true, last_error: null,
                spec: { greeting_text: "", menu_text: "", invalid_text: "", timeout_seconds: 5, max_tries: 3, voice_workflow_id: null,
                    fallback: { type: "hangup", target_id: null },
                    choices: [{ digit: "1", label: "Les ventes", type: "queue", target_id: 1 }] },
            },
        ],
    });
    mocks.aiOutbound.mockResolvedValue({
        data: { mode: "routes", trunk_id: null, dial_string_template: "Local/{number}@to-extern", number_format: "national", country_code: "225", national_prefix: "", caller_id: "+2252722000000", example: { number: "+2250707112233", dial_string: "Local/0707112233@to-extern" } },
    });
    mocks.groups.mockResolvedValue({
        data: {
            strategies: { all: "Tous les postes en même temps", linear: "Dans l'ordre de la liste" },
            groups: [{ id: 30, uuid: "g-1", label: "Accueil", extensions: ["4001"], strategy: "linear", ring_seconds: 15, members: [{ uuid: "u-1", name: "Koffi Yao" }], fallback: { type: "ai", target_id: 4, workflow_name: "Accueil" } }],
        },
    });
    mocks.conferences.mockResolvedValue({
        data: { live_error: null, conferences: [{ id: 60, name: "Point hebdo", extensions: ["5001"], has_pin: true, has_admin_pin: false, max_users: 10, record: false, participants: [{ id: "p-1", name: "Aya", number: "1002", muted: true, admin: false, joined_at: null }] }] },
    });
    mocks.callSettings.mockResolvedValue({
        data: { user_id: 1, name: "Koffi Yao", dnd: true, unanswered: null, forwards: { unconditional: { enabled: false, destination: "" }, busy: { enabled: false, destination: "" }, noanswer: { enabled: true, destination: "1002" } } },
    });
    mocks.restrictions.mockResolvedValue({
        data: { presets: [], restrictions: [{ id: 70, name: "Accueil", mode: "deny", patterns: ["_00."], enabled: true, has_pin: true, users: [{ uuid: "u-1", name: "Koffi Yao" }] }] },
    });
    mocks.voicemails.mockResolvedValue({ data: [{ id: 1, name: "Accueil", number: "1000" }] });
    mocks.trunks.mockResolvedValue({
        data: { status_error: null, trunks: [{ id: 40, label: "Orange", technology: "sip", host: "sip.orange.ci", username: "2252700", registration: true, registered: true, current_calls: 1, outcalls: ["Sortie"], caller_id_format: "+E164" }] },
    });
    mocks.routes.mockResolvedValue({
        data: { presets: [], routes: [{ id: 50, name: "Sortie", enabled: true, internal_caller_id: false, trunks: [{ id: 40, label: "Orange" }], rules: [{ pattern: "_0XXXXXXXXX", strip_digits: 0, prefix: "", external_prefix: "", caller_id: "+22527000000" }] }] },
    });
    for (const m of [mocks.setNumber, mocks.removeNumber, mocks.unroute, mocks.branding, mocks.events, mocks.hangup, mocks.agent]) m.mockResolvedValue({ data: {} });
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

        fireEvent.click(screen.getByRole("button", { name: /Ajouter un numéro/ }));
        fireEvent.change(await screen.findByLabelText("Numéro"), { target: { value: "+22527000100" } });
        selectOption(screen.getByRole("combobox", { name: "Destination du numéro — cible" }), "Recouvrement");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /^Enregistrer$/ }));
        });
        expect(mocks.setNumber).toHaveBeenCalledWith({
            body: { number: "+22527000100", destination: { type: "ai", target_id: 6 } },
        });
    });

    it("points an existing number at a voice menu and deletes a number", async () => {
        mocks.inventory.mockResolvedValue({
            data: {
                ...inventory,
                numbers: [{ ...inventory.numbers[0], destination: "Serveur vocal", destination_type: "ivr", destination_target_id: 31 }],
            },
        });
        render(<PbxPage />);
        await screen.findByTestId("pbx-call");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Numéros/ }));
        const row = (await screen.findAllByTestId("pbx-number"))[0];
        await waitFor(() => expect(row.textContent).toContain("Serveur vocal « Accueil »"));
        fireEvent.click(within(row).getByRole("button", { name: /Modifier la destination/ }));
        expect((await screen.findByLabelText("Numéro") as HTMLInputElement).disabled).toBe(true);
        selectOption(screen.getByRole("combobox", { name: "Destination du numéro — type" }), "File d'attente");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /^Enregistrer$/ }));
        });
        expect(mocks.setNumber).toHaveBeenCalledWith({
            body: { number: "+22527000000", destination: { type: "queue", target_id: 1 } },
        });
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: /Supprimer le numéro/ }));
        });
        expect(mocks.removeNumber).toHaveBeenCalledWith({ path: { number: "+22527000000" } });
    });

    it("shows voice menus and operator lines", async () => {
        render(<PbxPage />);
        await screen.findByTestId("pbx-call");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Serveurs vocaux/ }));
        const menu = await screen.findByTestId("pbx-menu");
        expect(menu.textContent).toContain("Publié");
        expect(menu.textContent).toContain("Pour les ventes, tapez 1.");
        expect(menu.textContent).toContain("File d'attente · Ventes (3001)");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Lignes opérateurs/ }));
        const trunk = await screen.findByTestId("pbx-trunk");
        expect(trunk.textContent).toContain("Enregistrée");
        expect(trunk.textContent).toContain("sip.orange.ci");
        expect((await screen.findByTestId("pbx-route")).textContent).toContain("1. Orange");
        expect((await screen.findByTestId("ai-outbound-preview")).textContent).toContain("compose 0707112233 via les routes sortantes, présenté +2252722000000");
        expect((await screen.findByTestId("pbx-restriction")).textContent).toContain("Interdit : _00.");
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

    it("shows call groups, live conferences and a user's forwards", async () => {
        render(<PbxPage />);
        await screen.findByTestId("pbx-call");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Groupes/ }));
        const group = await screen.findByTestId("pbx-group");
        expect(group.textContent).toContain("1. Koffi Yao");
        expect(group.textContent).toContain("Agent IA « Accueil »");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Conférences/ }));
        const room = await screen.findByTestId("pbx-conference");
        expect(room.textContent).toContain("1 en ligne");
        expect(within(room).getByRole("button", { name: "Rendre la parole à Aya" })).toBeTruthy();
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Postes/ }));
        fireEvent.click(await screen.findByRole("button", { name: "Renvois de Koffi Yao" }));
        await screen.findByTestId("call-settings");
        expect(mocks.callSettings).toHaveBeenCalledWith({ path: { user_id: 1 } });
        expect((screen.getByRole("switch", { name: "Ne pas déranger" }) as HTMLButtonElement).getAttribute("data-state")).toBe("checked");
        expect((screen.getByLabelText("Numéro du renvoi si pas de réponse") as HTMLInputElement).value).toBe("1002");
    });
});

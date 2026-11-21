import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SupervisionPage from "./page";

const mocks = vi.hoisted(() => ({
    snapshot: vi.fn(),
    events: vi.fn(),
    action: vi.fn(),
    spy: vi.fn(),
    pbxLive: vi.fn(),
    pbxSettings: vi.fn(),
    pbxSaveSettings: vi.fn(),
    pbxSpy: vi.fn(),
    pbxSessions: vi.fn(),
    pbxStats: vi.fn(),
    agentAction: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ loading: false, user: { id: "u" }, getAccessToken: async () => "jwt" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    snapshotApiV1SupervisionGet: mocks.snapshot,
    spyApiV1SupervisionSpyPost: mocks.spy,
    callEventsApiV1SupervisionCallsRunIdEventsGet: mocks.events,
    callActionApiV1SupervisionCallsRunIdActionsPost: mocks.action,
    readLiveApiV1PbxSupervisionLiveGet: mocks.pbxLive,
    readSettingsApiV1PbxSupervisionSettingsGet: mocks.pbxSettings,
    saveSettingsApiV1PbxSupervisionSettingsPut: mocks.pbxSaveSettings,
    spyApiV1PbxSupervisionSpyPost: mocks.pbxSpy,
    listSessionsApiV1PbxSupervisionSessionsGet: mocks.pbxSessions,
    readStatisticsApiV1PbxSupervisionStatisticsGet: mocks.pbxStats,
    agentActionApiV1PbxAgentsAgentNumberActionPost: mocks.agentAction,
}));

const PBX_CALL = {
    call_id: "c1",
    user_uuid: "u-1",
    user_name: "Koffi Yao",
    extension: "1001",
    with_number: "+2250700112233",
    with_name: "Awa",
    direction: "inbound",
    state: "on_call",
    seconds: 65,
    on_hold: false,
    recording: false,
    spyable: true,
};

function pbxLive(overrides: Record<string, unknown> = {}) {
    return {
        queues: [
            {
                id: 1,
                name: "Ventes",
                number: "3001",
                live: true,
                waiting: 1,
                longest_wait_seconds: 42,
                callers: [{ position: 1, number: "+2250102030405", name: "Ibrahim Touré", wait_seconds: 42 }],
                agents_available: 0,
                agents_on_call: 1,
                agents_paused: 0,
                agents_logged: 1,
                members: 1,
                sla_seconds: 20,
            },
        ],
        agents: [
            {
                id: 7,
                number: "1001",
                name: "Koffi Yao",
                user_uuid: "u-1",
                extension: "1001",
                state: "on_call",
                paused_reason: null,
                call: PBX_CALL,
            },
            {
                id: 8,
                number: "1003",
                name: "Mariam Traoré",
                user_uuid: "u-3",
                extension: "1003",
                state: "available",
                paused_reason: null,
                call: null,
            },
        ],
        calls: [PBX_CALL],
        kpis: {
            calls: 1,
            waiting: 1,
            longest_wait_seconds: 42,
            agents_available: 1,
            agents_on_call: 1,
            agents_paused: 0,
            agents_logged_out: 0,
        },
        listening: { enabled: true, modes: ["listen", "whisper"], supervisors: [] },
        errors: {},
        ...overrides,
    };
}

beforeEach(() => {
    vi.clearAllMocks();
    // No WebSocket here: the console falls back to polling (same screen).
    vi.stubGlobal("WebSocket", undefined);
    mocks.pbxLive.mockResolvedValue({ error: { detail: "Aucun PBX connecté" }, response: { status: 404 } });
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

    it("adds the enterprise PBX: live queues, agents, listening and statistics", async () => {
        mocks.pbxLive.mockResolvedValue({ data: pbxLive() });
        mocks.pbxSettings.mockResolvedValue({
            data: {
                enabled: true,
                modes: ["listen", "whisper"],
                supervisors: [],
                protected: [],
                notice_acknowledged: true,
                sla_seconds: 20,
                my_extension: "u-2",
                extensions: [
                    { uuid: "u-1", name: "Koffi Yao", extension: "1001" },
                    { uuid: "u-2", name: "Aya Diallo", extension: "1002" },
                ],
            },
        });
        mocks.pbxSpy.mockResolvedValue({ data: { status: "ringing" } });
        mocks.agentAction.mockResolvedValue({ data: null });
        mocks.pbxStats.mockResolvedValue({
            data: {
                period: "today",
                sla_seconds: 20,
                timezone: "Africa/Abidjan",
                queues: [
                    {
                        queue_id: 1,
                        name: "Ventes",
                        received: 40,
                        answered: 34,
                        abandoned: 4,
                        unanswered: 1,
                        closed: 1,
                        average_wait_seconds: 27,
                        answered_rate: 87.18,
                        service_level: 76.47,
                    },
                ],
                agents: [
                    {
                        agent_id: 7,
                        name: "Koffi Yao",
                        number: "1001",
                        answered: 21,
                        conversation_seconds: 4380,
                        average_talk_seconds: 208,
                        login_seconds: 25200,
                        pause_seconds: 1800,
                        occupancy: 17.4,
                    },
                ],
                totals: { received: 40, answered: 34, abandoned: 4, answered_rate: 87.2, service_level: 76.5, average_wait_seconds: 27 },
            },
        });
        render(<SupervisionPage />);
        await waitFor(() => expect(screen.getByTestId("pbx-supervision")).toBeTruthy());
        expect(screen.getByTestId("stream-mode").textContent).toContain("5 s");

        // One picture: the built-in contact center and the PBX together.
        expect(screen.getByTestId("kpi-En attente").textContent).toContain("3");
        expect(screen.getByTestId("kpi-Appels conseillers").textContent).toContain("2");
        expect(screen.getByTestId("pbx-live-queue").textContent).toContain("Ibrahim Touré");

        // The supervisor's own extension is preselected (e-mail match).
        await waitFor(() => expect(screen.getByLabelText("Votre poste").textContent).toContain("Aya Diallo"));
        const agentRow = screen.getAllByTestId("pbx-live-agent")[0];
        expect(agentRow.textContent).toContain("Awa");
        expect(screen.queryByRole("button", { name: /Intervenir Koffi/ })).toBeNull(); // mode not allowed
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Chuchoter Koffi Yao" }));
        });
        expect(mocks.pbxSpy).toHaveBeenCalledWith({
            body: { supervisor_user_uuid: "u-2", target_user_uuid: "u-1", mode: "whisper" },
        });

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Mettre Mariam Traoré en pause" }));
        });
        expect(mocks.agentAction).toHaveBeenCalledWith({
            path: { agent_number: "1003", action: "pause" },
            body: { reason: "Pause demandée par la supervision" },
        });

        await waitFor(() => expect(screen.getByTestId("queue-statistics")).toBeTruthy());
        expect(screen.getByTestId("stat-Taux de décroché").textContent).toContain("87 %");
        expect(screen.getByTestId("agent-stat").textContent).toContain("3:28");
        fireEvent.click(screen.getByRole("button", { name: "7 jours" }));
        await waitFor(() =>
            expect(mocks.pbxStats).toHaveBeenLastCalledWith({ query: { period: "7d" } }),
        );
    });

    it("explains when listening is off and lets an admin turn it on", async () => {
        mocks.pbxLive.mockResolvedValue({
            data: pbxLive({
                listening: { enabled: false, modes: ["listen"], supervisors: [] },
                calls: [{ ...PBX_CALL, spyable: false }],
                agents: [],
            }),
        });
        mocks.pbxSettings.mockResolvedValue({
            data: {
                enabled: false,
                modes: ["listen", "whisper", "barge"],
                supervisors: [],
                protected: [],
                notice_acknowledged: false,
                sla_seconds: 20,
                my_extension: null,
                extensions: [{ uuid: "u-1", name: "Koffi Yao", extension: "1001" }],
            },
        });
        mocks.pbxSaveSettings.mockImplementation(async ({ body }) => ({ data: body }));
        mocks.pbxStats.mockResolvedValue({ error: { detail: "PBX : accès refusé" } });
        render(<SupervisionPage />);
        await waitFor(() => expect(screen.getByTestId("pbx-supervision").textContent).toContain("désactivée"));
        expect(screen.queryByRole("button", { name: /^Écouter Koffi/ })).toBeNull();
        expect(screen.getByTestId("pbx-live-call").textContent).toContain("Koffi Yao");

        fireEvent.click(screen.getByRole("button", { name: /Réglages de l'écoute/ }));
        const enable = await screen.findByRole("switch");
        expect((enable as HTMLButtonElement).disabled).toBe(true); // notice first
        fireEvent.click(screen.getByRole("checkbox", { name: "Collaborateurs informés" }));
        fireEvent.click(screen.getByRole("switch"));
        fireEvent.click(screen.getByRole("checkbox", { name: "Intervenir" }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Postes jamais écoutés : Koffi Yao" }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.pbxSaveSettings).toHaveBeenCalledWith({
            body: {
                enabled: true,
                modes: ["listen", "whisper"],
                supervisors: [],
                protected: ["u-1"],
                notice_acknowledged: true,
                sla_seconds: 20,
            },
        });
        expect(screen.getByText("PBX : accès refusé")).toBeTruthy();
    });
});

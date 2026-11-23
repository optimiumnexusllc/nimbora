import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { lines, parseObject } from "@/lib/agentTests";

import AgentTestsPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    run: vi.fn(),
    suggest: vi.fn(),
    readRun: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("next/navigation", () => ({ useParams: () => ({ workflowId: "12" }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    listAgentTestsApiV1AgentTestsGet: mocks.list,
    createAgentTestApiV1AgentTestsPost: mocks.create,
    updateAgentTestApiV1AgentTestsTestIdPut: mocks.update,
    deleteAgentTestApiV1AgentTestsTestIdDelete: mocks.remove,
    runAgentTestsApiV1AgentTestsRunPost: mocks.run,
    suggestAgentTestsApiV1AgentTestsSuggestPost: mocks.suggest,
    readAgentTestRunApiV1AgentTestsRunsRunIdGet: mocks.readRun,
}));

const test1 = {
    id: 3,
    workflow_id: 12,
    name: "Client pressé",
    persona: "Tu es Awa, pressée, tu veux une chambre vue mer ce soir.",
    opening: null,
    success_criteria: ["Annonce le prix"],
    must_call: [],
    must_not_call: [],
    forbidden_phrases: [],
    mock_results: {},
    initial_context: {},
    max_turns: 8,
    last_run: { id: 9, test_id: 3, version: "draft", status: "failed", error: null, outcome_label: "Le client a terminé la conversation", summary: null, created_at: null, finished_at: null },
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: [test1] });
});

describe("agent test helpers", () => {
    it("reads lines and JSON objects", () => {
        expect(lines(" a \n\n b ")).toEqual(["a", "b"]);
        expect(parseObject("", "X")).toEqual({ value: {} });
        expect(parseObject("[1]", "X").error).toContain("objet JSON");
        expect(parseObject("{oops", "X").error).toBe("X : JSON invalide");
    });
});

describe("AgentTestsPage", () => {
    it("lists the tests, runs them on the chosen version and shows a run", async () => {
        mocks.run.mockResolvedValue({ data: [{ id: 10, status: "queued" }] });
        mocks.readRun.mockResolvedValue({
            data: {
                ...test1.last_run,
                result: {
                    outcome: "customer_ended",
                    outcome_label: "Le client a terminé la conversation",
                    transcript: [
                        { role: "agent", text: "Hôtel Horizon, bonjour !", node: "Accueil" },
                        { role: "customer", text: "Une chambre vue mer ?" },
                    ],
                    tool_calls: [{ name: "catalogue", arguments: { query: "vue mer" }, node: "Accueil" }],
                    visited_nodes: ["Accueil"],
                    failures: [],
                    checks: [],
                    criteria: [{ criterion: "Annonce le prix", passed: false, reason: "Aucun prix donné" }],
                    summary: "Accueil correct.",
                    notes: [],
                    metrics: { turns: 1, model_calls: 2, elapsed_ms: 1500 },
                },
            },
        });
        render(<AgentTestsPage />);
        const table = await screen.findByTestId("agent-tests");
        expect(table.textContent).toContain("Client pressé");
        expect(table.textContent).toContain("Échoué");

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Lancer tous les tests/ }));
        });
        expect(mocks.run).toHaveBeenCalledWith({ body: { workflow_id: 12, test_ids: null, version: "draft" } });

        fireEvent.click(within(table).getByText("Échoué"));
        const transcript = await screen.findByTestId("transcript");
        expect(transcript.textContent).toContain("Client simulé");
        expect(screen.getByTestId("verdicts").textContent).toContain("Aucun prix donné");
        expect(screen.getByText(/catalogue\(/).textContent).toContain('"query":"vue mer"');
    });

    it("creates a test and refuses invalid JSON", async () => {
        mocks.create.mockResolvedValue({ data: { id: 4 } });
        render(<AgentTestsPage />);
        await screen.findByTestId("agent-tests");
        fireEvent.click(screen.getByRole("button", { name: /Nouveau test/ }));
        fireEvent.change(await screen.findByLabelText("Nom du test"), { target: { value: "Hors sujet" } });
        fireEvent.change(screen.getByLabelText("Le client"), { target: { value: "Tu demandes la météo de demain." } });
        fireEvent.change(screen.getByLabelText("Critères de réussite"), { target: { value: "Recentre poliment\n\nReste courtois" } });
        fireEvent.change(screen.getByLabelText(/Résultats simulés/), { target: { value: "{pas du json" } });
        fireEvent.click(screen.getByRole("button", { name: /Enregistrer le test/ }));
        expect(screen.getByRole("alert").textContent).toBe("Résultats simulés : JSON invalide");
        fireEvent.change(screen.getByLabelText(/Résultats simulés/), { target: { value: "" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer le test/ }));
        });
        await waitFor(() => expect(mocks.create).toHaveBeenCalled());
        const body = mocks.create.mock.calls[0][0].body;
        expect(body).toMatchObject({ workflow_id: 12, name: "Hors sujet", success_criteria: ["Recentre poliment", "Reste courtois"], mock_results: {} });
    });

    it("adds a suggested test", async () => {
        mocks.suggest.mockResolvedValue({ data: [{ ...test1, name: "Nominal" }] });
        mocks.create.mockResolvedValue({ data: { id: 5 } });
        render(<AgentTestsPage />);
        await screen.findByTestId("agent-tests");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Proposer des tests/ }));
        });
        const list = await screen.findByTestId("suggestions");
        await act(async () => {
            fireEvent.click(within(list).getByRole("button", { name: /Ajouter/ }));
        });
        expect(mocks.create.mock.calls[0][0].body.name).toBe("Nominal");
        expect(screen.getByText("Toutes les propositions ont été ajoutées.")).toBeTruthy();
    });
});

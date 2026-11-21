import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { QueuesTab } from "./QueuesTab";

const mocks = vi.hoisted(() => ({
    strategies: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    overflow: vi.fn(),
    add: vi.fn(),
    drop: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    strategiesApiV1PbxStrategiesGet: mocks.strategies,
    createQueueApiV1PbxQueuesPost: mocks.create,
    deleteQueueApiV1PbxQueuesQueueIdDelete: mocks.remove,
    queueOverflowApiV1PbxQueuesQueueIdOverflowPut: mocks.overflow,
    addQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdPut: mocks.add,
    removeQueueMemberApiV1PbxQueuesQueueIdMembersAgentIdDelete: mocks.drop,
}));

const agents = [
    { id: 7, number: "1001", name: "Koffi Yao", logged: true, paused: false, paused_reason: null, extension: "1001" },
    { id: 8, number: "1003", name: "Mariam Traoré", logged: false, paused: false, paused_reason: null, extension: null },
];
const workflows = [{ id: 4, name: "Accueil IA" }];
const queues = [
    { id: 1, name: "Ventes", extensions: ["3001"], members: 1, agent_ids: [7], wait_time_threshold: 45, overflow: { workflow_id: 4, workflow_name: "Accueil IA" } },
];

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.strategies.mockResolvedValue({ data: { leastrecent: "Le conseiller libre depuis le plus longtemps", rrmemory: "Chacun son tour" } });
    for (const m of [mocks.create, mocks.remove, mocks.overflow, mocks.add, mocks.drop]) m.mockResolvedValue({ data: {} });
});

describe("queues tab", () => {
    it("shows the AI overflow of a queue", () => {
        render(<QueuesTab queues={queues} agents={agents} workflows={workflows} aiEnabled onChanged={vi.fn()} />);
        expect(screen.getByTestId("pbx-queue").textContent).toContain("Accueil IA après 45 s");
    });

    it("creates a queue with members and an overflow to an AI agent", async () => {
        render(<QueuesTab queues={[]} agents={agents} workflows={workflows} aiEnabled onChanged={vi.fn()} />);
        await waitFor(() => expect(mocks.strategies).toHaveBeenCalled());
        fireEvent.click(screen.getByRole("button", { name: /Nouvelle file/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Service client" } });
        fireEvent.change(screen.getByLabelText("Numéro interne"), { target: { value: "3005" } });
        selectOption(screen.getByRole("combobox", { name: "Stratégie" }), "Chacun son tour");
        fireEvent.click(screen.getByRole("checkbox", { name: "Mariam Traoré" }));
        selectOption(screen.getByRole("combobox", { name: "Agent IA de débordement" }), "Accueil IA");
        fireEvent.change(screen.getByLabelText(/Après \(secondes/), { target: { value: "90" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Créer la file" }));
        });
        expect(mocks.create).toHaveBeenCalledWith({
            body: { label: "Service client", extension: "3005", strategy: "rrmemory", ring_seconds: 20, agent_ids: [8], overflow_workflow_id: 4, overflow_after_seconds: 90 },
        });
    });

    it("edits members and removes the overflow", async () => {
        render(<QueuesTab queues={queues} agents={agents} workflows={workflows} aiEnabled onChanged={vi.fn()} />);
        const row = screen.getByTestId("pbx-queue");
        fireEvent.click(within(row).getByRole("button", { name: /Membres/ }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Koffi Yao" }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Mariam Traoré" }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.add).toHaveBeenCalledWith({ path: { queue_id: 1, agent_id: 8 } });
        expect(mocks.drop).toHaveBeenCalledWith({ path: { queue_id: 1, agent_id: 7 } });

        fireEvent.click(within(row).getByRole("button", { name: /Débordement IA/ }));
        selectOption(screen.getByRole("combobox", { name: "Agent IA" }), "Pas de débordement");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.overflow).toHaveBeenCalledWith({ path: { queue_id: 1 }, body: { workflow_id: null, after_seconds: 45 } });
    });

    it("needs AI access for overflows", () => {
        render(<QueuesTab queues={queues} agents={agents} workflows={workflows} aiEnabled={false} onChanged={vi.fn()} />);
        expect(within(screen.getByTestId("pbx-queue")).getByRole("button", { name: /Débordement IA/ })).toHaveProperty("disabled", true);
    });
});

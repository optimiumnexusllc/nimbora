import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { TransferTargetPicker } from "./TransferTargetPicker";

const mocks = vi.hoisted(() => ({ targets: vi.fn(), queues: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("@/client/sdk.gen", () => ({ transferTargetsApiV1PbxTransferTargetsGet: mocks.targets }));
vi.mock("@/lib/enterpriseApi", () => ({ enterpriseApi: { listQueues: mocks.queues } }));

beforeEach(() => {
    vi.clearAllMocks();
});

describe("TransferTargetPicker", () => {
    it("lists PBX queues and extensions and contact-center queues, and fills the destination", async () => {
        mocks.targets.mockResolvedValue({
            data: [
                { destination: "pbx-queue:1", kind: "pbx_queue", label: "Ventes", number: "3001" },
                { destination: "pbx-extension:1002", kind: "pbx_extension", label: "Aya Diallo", number: "1002" },
            ],
        });
        mocks.queues.mockResolvedValue([{ id: 1, slug: "support", name: "Support client" }]);
        const onPick = vi.fn();
        render(<TransferTargetPicker value="" onPick={onPick} />);
        await waitFor(() => expect(screen.getByTestId("transfer-target-picker")).toBeTruthy());
        await selectOption(screen.getByLabelText("Choisir une file ou un poste de l'entreprise"), "Ventes · 3001");
        expect(onPick).toHaveBeenCalledWith("pbx-queue:1");
        await selectOption(screen.getByLabelText("Choisir une file ou un poste de l'entreprise"), "Support client");
        expect(onPick).toHaveBeenLastCalledWith("queue:support");
    });

    it("stays hidden without any company destination", async () => {
        mocks.targets.mockResolvedValue({ error: { detail: "Aucun PBX connecté" } });
        mocks.queues.mockRejectedValue(new Error("404"));
        const { container } = render(<TransferTargetPicker value="" onPick={vi.fn()} />);
        await waitFor(() => expect(mocks.queues).toHaveBeenCalled());
        expect(container.innerHTML).toBe("");
    });
});

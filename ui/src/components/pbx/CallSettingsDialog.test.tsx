import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { CallSettingsDialog } from "./CallSettingsDialog";
import type { DestinationSources } from "./DestinationPicker";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    readCallSettingsApiV1PbxExtensionsUserIdCallSettingsGet: mocks.read,
    saveCallSettingsApiV1PbxExtensionsUserIdCallSettingsPut: mocks.save,
}));

const user = { id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true };
const sources: DestinationSources = {
    queues: [], users: [user], voicemails: [{ id: 1, name: "Koffi", number: "1001" }],
    workflows: [{ id: 4, name: "Assistante IA" } as never], menus: [], aiEnabled: true,
};
const off = { enabled: false, destination: "" };

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: { user_id: 1, name: "Koffi Yao", dnd: false, unanswered: null, forwards: { unconditional: off, busy: off, noanswer: off } } });
    mocks.save.mockResolvedValue({ data: {} });
});

describe("CallSettingsDialog", () => {
    it("sets a forward, do-not-disturb and an AI agent for unanswered calls", async () => {
        const onClose = vi.fn();
        render(<CallSettingsDialog user={user} onClose={onClose} sources={sources} />);
        await screen.findByTestId("call-settings");
        fireEvent.click(screen.getByRole("switch", { name: "Renvoi si occupé" }));
        const save = screen.getByRole("button", { name: "Enregistrer" });
        expect(save).toHaveProperty("disabled", true);
        expect(screen.getByText("Renvoi « Si occupé » : indiquez le numéro.")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Numéro du renvoi si occupé"), { target: { value: "1002" } });
        fireEvent.click(screen.getByRole("switch", { name: "Ne pas déranger" }));
        fireEvent.click(screen.getByRole("switch", { name: "Rediriger les appels sans réponse" }));
        expect(screen.getByText(/L'agent IA décroche à la place de Koffi Yao/)).toBeTruthy();
        selectOption(screen.getByRole("combobox", { name: "Destination sans réponse — type" }), "Messagerie");
        selectOption(screen.getByRole("combobox", { name: "Destination sans réponse — type" }), "Agent IA");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.save).toHaveBeenCalledWith({
            path: { user_id: 1 },
            body: {
                unconditional: off,
                busy: { enabled: true, destination: "1002" },
                noanswer: off,
                dnd: true,
                unanswered: { type: "ai", target_id: 4 },
                unanswered_mode: "set",
            },
        });
        expect(onClose).toHaveBeenCalled();
    });
});

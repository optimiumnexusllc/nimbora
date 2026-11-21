import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { ScheduleDialog } from "./ScheduleDialog";

const mocks = vi.hoisted(() => ({ voicemails: vi.fn(), sync: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    listVoicemailsApiV1PbxVoicemailsGet: mocks.voicemails,
    syncScheduleApiV1PbxSchedulePut: mocks.sync,
}));

const numbers = [
    { number: "+22527000000", incall_id: 5, description: "Standard", destination: "File d'attente", ai_workflow_id: null, ai_workflow_name: null },
    { number: "+22527000001", incall_id: 6, description: null, destination: "File d'attente", ai_workflow_id: null, ai_workflow_name: null },
    { number: "+22527000099", incall_id: 9, description: null, destination: "Agent IA", ai_workflow_id: 4, ai_workflow_name: "Accueil" },
];

beforeEach(() => {
    vi.clearAllMocks();
    mocks.voicemails.mockResolvedValue({ data: [{ id: 1, name: "Accueil", number: "1000" }] });
    mocks.sync.mockResolvedValue({ data: { open_periods: 11, closures: 2 } });
});

describe("opening hours dialog", () => {
    it("applies the company hours with an AI agent outside them", async () => {
        const onDone = vi.fn();
        render(<ScheduleDialog open onOpenChange={vi.fn()} numbers={numbers} workflows={[{ id: 4, name: "Accueil IA" }]} aiEnabled onDone={onDone} />);
        await waitFor(() => expect(mocks.voicemails).toHaveBeenCalled());
        // Numbers already answered by an AI agent are not offered.
        expect(screen.queryByRole("checkbox", { name: "+22527000099" })).toBeNull();
        fireEvent.click(screen.getByRole("checkbox", { name: "+22527000001" }));
        const apply = screen.getByRole("button", { name: "Appliquer les horaires" });
        expect(apply).toHaveProperty("disabled", true);
        selectOption(screen.getByRole("combobox", { name: "Agent IA hors horaires" }), "Accueil IA");
        await act(async () => {
            fireEvent.click(apply);
        });
        expect(mocks.sync).toHaveBeenCalledWith({ body: { incall_ids: [5], closed: "ai_agent", workflow_id: 4, voicemail_id: null } });
        expect(mocks.toast.success).toHaveBeenCalledWith("Horaires appliqués : 11 plage(s), 2 fermeture(s)");
        expect(onDone).toHaveBeenCalled();
    });

    it("can send closed hours to a voicemail", async () => {
        render(<ScheduleDialog open onOpenChange={vi.fn()} numbers={numbers} workflows={[]} aiEnabled={false} onDone={vi.fn()} />);
        await waitFor(() => expect(mocks.voicemails).toHaveBeenCalled());
        expect(screen.queryByRole("radio", { name: "Un agent IA répond" })).toBeNull();
        selectOption(screen.getByRole("combobox", { name: "Messagerie hors horaires" }), /Accueil/);
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Appliquer les horaires" }));
        });
        expect(mocks.sync).toHaveBeenCalledWith({ body: { incall_ids: [5, 6], closed: "voicemail", workflow_id: null, voicemail_id: 1 } });
    });
});

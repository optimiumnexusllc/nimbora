import "@/components/model-connections/test-helpers";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordingsTab } from "./RecordingsTab";

const mocks = vi.hoisted(() => ({
    list: vi.fn(), policy: vi.fn(), sync: vi.fn(), audio: vi.fn(), remove: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    listRecordingsApiV1PbxRecordingsGet: mocks.list,
    saveRecordingPolicyApiV1PbxRecordingsPolicyPut: mocks.policy,
    syncRecordingsApiV1PbxRecordingsSyncPost: mocks.sync,
    recordingAudioApiV1PbxRecordingsRecordingIdAudioGet: mocks.audio,
    deleteRecordingApiV1PbxRecordingsRecordingIdDelete: mocks.remove,
}));

const users = [
    { id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true },
    { id: 2, uuid: "u-2", name: "Aya Diallo", extension: "1002", email: null, enabled: true },
];
const policy = {
    incoming_external: false, outgoing_external: false, internal: false, user_uuids: null,
    import_enabled: true, transcribe: false, remove_from_pbx: false,
};
const recording = {
    id: 7, started_at: "2026-11-21T09:00:00Z", duration_seconds: 125, direction: "inbound",
    source: "+2250700112233", source_name: "Awa", destination: "1001", destination_name: "Koffi Yao",
    customer_phone: "+2250700112233", size_bytes: 1000,
    transcript: "Ma carte est [CARD], merci.", transcript_status: "done", removed_from_pbx: true,
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.list.mockResolvedValue({ data: { items: [recording], total: 1, policy, synced_at: "2026-11-21T09:10:00Z" } });
    mocks.policy.mockResolvedValue({ data: { policy, extensions_changed: 1 } });
    mocks.sync.mockResolvedValue({ data: { imported: 2, seen: 3 } });
    mocks.audio.mockResolvedValue({ data: { url: "https://storage.local/r.wav" } });
    mocks.remove.mockResolvedValue({ data: null });
});

describe("RecordingsTab", () => {
    it("records chosen extensions and keeps a masked transcript", async () => {
        render(<RecordingsTab users={users} />);
        await screen.findByTestId("recording-policy");
        fireEvent.click(screen.getByRole("switch", { name: "Appels reçus de l'extérieur" }));
        expect(screen.getByText(/Informez vos correspondants/)).toBeTruthy();
        fireEvent.click(screen.getByRole("radio", { name: "Certains postes" }));
        expect(screen.getByRole("button", { name: /Appliquer/ })).toHaveProperty("disabled", true);
        fireEvent.click(screen.getByRole("checkbox", { name: "Aya Diallo" }));
        fireEvent.click(screen.getByRole("switch", { name: "Transcrire les appels" }));
        fireEvent.click(screen.getByRole("switch", { name: "Retirer du PBX" }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Appliquer/ }));
        });
        expect(mocks.policy).toHaveBeenCalledWith({
            body: { ...policy, incoming_external: true, user_uuids: ["u-2"], transcribe: true, remove_from_pbx: true },
        });
        expect(mocks.toast.success).toHaveBeenCalledWith("Réglage appliqué à 1 poste(s)");
    });

    it("lists, plays, shows the transcript, imports and deletes", async () => {
        render(<RecordingsTab users={users} />);
        const row = await screen.findByTestId("pbx-recording");
        expect(row.textContent).toContain("Awa (+2250700112233) → Koffi Yao (1001)");
        expect(row.textContent).toContain("2 min 05 s");
        expect(row.textContent).toContain("copie unique");
        fireEvent.click(within(row).getByRole("button", { name: /Transcription/ }));
        expect(screen.getByTestId("recording-transcript").textContent).toBe("Ma carte est [CARD], merci.");
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: "Écouter l'appel 7" }));
        });
        expect((screen.getByTestId("recording-audio") as HTMLAudioElement).src).toBe("https://storage.local/r.wav");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Importer maintenant/ }));
        });
        expect(mocks.toast.success).toHaveBeenCalledWith("2 enregistrement(s) importé(s)");
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: "Supprimer l'enregistrement 7" }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { recording_id: 7 } });
    });
});

import "@/components/model-connections/test-helpers";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConferencesTab, type PbxConference } from "./ConferencesTab";

const mocks = vi.hoisted(() => ({
    create: vi.fn(), remove: vi.fn(), action: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    createConferenceApiV1PbxConferencesPost: mocks.create,
    deleteConferenceApiV1PbxConferencesConferenceIdDelete: mocks.remove,
    conferenceParticipantActionApiV1PbxConferencesConferenceIdParticipantsParticipantIdActionPost: mocks.action,
}));

const room: PbxConference = {
    id: 60, name: "Codir", extensions: ["5001"], has_pin: true, has_admin_pin: true, max_users: 10, record: false,
    participants: [
        { id: "p-1", name: "Koffi Yao", number: "1001", muted: false, admin: true, joined_at: "2026-11-21T09:00:00Z" },
        { id: "p-2", name: "+2250707112233", number: "+2250707112233", muted: true, admin: false, joined_at: "2026-11-21T09:05:00Z" },
    ],
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    for (const m of [mocks.create, mocks.remove, mocks.action]) m.mockResolvedValue({ data: {} });
});

describe("ConferencesTab", () => {
    it("shows who is in the room and controls microphones", async () => {
        const onChanged = vi.fn();
        render(<ConferencesTab conferences={[room]} onChanged={onChanged} now={new Date("2026-11-21T09:10:00Z").getTime()} />);
        const card = screen.getByTestId("pbx-conference");
        expect(card.textContent).toContain("2 en ligne");
        expect(card.textContent).toContain("Code d'accès");
        expect(within(card).getByTestId("conference-participants").textContent).toContain("10:00");
        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: "Couper le micro de Koffi Yao" }));
        });
        expect(mocks.action).toHaveBeenCalledWith({ path: { conference_id: 60, participant_id: "p-1", action: "mute" } });
        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: "Rendre la parole à +2250707112233" }));
        });
        expect(mocks.action).toHaveBeenLastCalledWith({ path: { conference_id: 60, participant_id: "p-2", action: "unmute" } });
        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: "Faire sortir +2250707112233" }));
        });
        expect(mocks.action).toHaveBeenLastCalledWith({ path: { conference_id: 60, participant_id: "p-2", action: "kick" } });
        expect(onChanged).toHaveBeenCalledTimes(3);
    });

    it("creates a room with access codes", async () => {
        render(<ConferencesTab conferences={[]} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Nouvelle salle/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Point hebdo" } });
        fireEvent.change(screen.getByLabelText("Numéro"), { target: { value: "5002" } });
        fireEvent.change(screen.getByLabelText("Code participants"), { target: { value: "12" } });
        expect(screen.getByText("Codes : 4 à 12 chiffres")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Code participants"), { target: { value: "2468" } });
        fireEvent.change(screen.getByLabelText("Code organisateur"), { target: { value: "2468" } });
        expect(screen.getByText("Le code organisateur doit différer")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Code organisateur"), { target: { value: "1357" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Créer la salle/ }));
        });
        expect(mocks.create).toHaveBeenCalledWith({
            body: { name: "Point hebdo", extension: "5002", pin: "2468", admin_pin: "1357", max_users: 0, record: false, announce_join_leave: true, announce_user_count: true },
        });
    });
});

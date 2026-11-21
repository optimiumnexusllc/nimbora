import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import type { DestinationSources } from "./DestinationPicker";
import { GroupsTab, type PbxGroup } from "./GroupsTab";

const mocks = vi.hoisted(() => ({
    create: vi.fn(), members: vi.fn(), fallback: vi.fn(), remove: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    createGroupApiV1PbxGroupsPost: mocks.create,
    setGroupMembersApiV1PbxGroupsGroupUuidMembersPut: mocks.members,
    setGroupFallbackApiV1PbxGroupsGroupUuidFallbackPut: mocks.fallback,
    deleteGroupApiV1PbxGroupsGroupUuidDelete: mocks.remove,
}));

const users = [
    { id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true },
    { id: 2, uuid: "u-2", name: "Aya Diallo", extension: "1002", email: null, enabled: true },
];
const sources: DestinationSources = {
    queues: [{ id: 1, name: "Ventes", extensions: ["3001"], members: 1 }],
    users,
    voicemails: [{ id: 1, name: "Accueil", number: "1000" }],
    workflows: [{ id: 4, name: "Assistante IA" } as never],
    menus: [],
    aiEnabled: true,
};
const strategies = { all: "Tous les postes en même temps", linear: "Dans l'ordre de la liste" };
const group: PbxGroup = {
    id: 30, uuid: "g-1", label: "Accueil", extensions: ["4001"], strategy: "all", ring_seconds: 20,
    members: [{ uuid: "u-1", name: "Koffi Yao" }], fallback: { type: "voicemail", target_id: 1 },
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    for (const m of [mocks.create, mocks.members, mocks.fallback, mocks.remove]) m.mockResolvedValue({ data: {} });
});

describe("GroupsTab", () => {
    it("creates a group ringing in order, with an AI agent when nobody answers", async () => {
        render(<GroupsTab groups={[]} strategies={strategies} users={users} sources={sources} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Nouveau groupe/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Équipe accueil" } });
        fireEvent.change(screen.getByLabelText("Numéro"), { target: { value: "4001" } });
        selectOption(screen.getByRole("combobox", { name: "Façon de sonner" }), "Dans l'ordre de la liste");
        fireEvent.click(screen.getByRole("checkbox", { name: "Koffi Yao" }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Aya Diallo" }));
        fireEvent.click(screen.getByRole("button", { name: "Monter Aya Diallo" }));
        expect(screen.getByTestId("group-order").textContent).toMatch(/1\s*Aya Diallo.*2\s*Koffi Yao/);
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Créer le groupe/ }));
        });
        expect(mocks.create).toHaveBeenCalledWith({
            body: {
                label: "Équipe accueil", extension: "4001", strategy: "linear", ring_seconds: 20,
                user_uuids: ["u-2", "u-1"], fallback: { type: "ai", target_id: 4 },
            },
        });
    });

    it("changes members and the no-answer destination, and deletes", async () => {
        const onChanged = vi.fn();
        render(<GroupsTab groups={[group]} strategies={strategies} users={users} sources={sources} onChanged={onChanged} />);
        const card = screen.getByTestId("pbx-group");
        expect(card.textContent).toContain("Messagerie · Accueil (1000)");
        fireEvent.click(within(card).getByRole("button", { name: /Membres/ }));
        fireEvent.click(within(screen.getByRole("dialog")).getByRole("checkbox", { name: "Aya Diallo" }));
        await act(async () => {
            fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.members).toHaveBeenCalledWith({ path: { group_uuid: "g-1" }, body: { user_uuids: ["u-1", "u-2"] } });

        fireEvent.click(within(card).getByRole("button", { name: /Sans réponse/ }));
        fireEvent.click(screen.getByRole("switch", { name: "Rediriger l'appel" }));
        await act(async () => {
            fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.fallback).toHaveBeenCalledWith({ path: { group_uuid: "g-1" }, body: { fallback: null } });

        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: "Supprimer Accueil" }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { group_uuid: "g-1" } });
        expect(onChanged).toHaveBeenCalled();
    });
});

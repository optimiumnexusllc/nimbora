import "@/components/model-connections/test-helpers";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RestrictionsSection } from "./RestrictionsSection";

const mocks = vi.hoisted(() => ({
    list: vi.fn(), create: vi.fn(), users: vi.fn(), remove: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    listRestrictionsApiV1PbxRestrictionsGet: mocks.list,
    createRestrictionApiV1PbxRestrictionsPost: mocks.create,
    setRestrictionUsersApiV1PbxRestrictionsPermissionIdUsersPut: mocks.users,
    deleteRestrictionApiV1PbxRestrictionsPermissionIdDelete: mocks.remove,
}));

const users = [
    { id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true },
    { id: 2, uuid: "u-2", name: "Aya Diallo", extension: "1002", email: null, enabled: true },
];

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.list.mockResolvedValue({
        data: {
            presets: [{ id: "international", label: "Pas d'appels internationaux", mode: "deny", patterns: ["_00.", "_+X."] }],
            restrictions: [{ id: 70, name: "Accueil", mode: "deny", patterns: ["_08."], enabled: true, has_pin: false, users: [{ uuid: "u-1", name: "Koffi Yao" }] }],
        },
    });
    for (const m of [mocks.create, mocks.users, mocks.remove]) m.mockResolvedValue({ data: {} });
});

describe("RestrictionsSection", () => {
    it("creates a restriction from a preset for chosen extensions", async () => {
        render(<RestrictionsSection users={users} />);
        expect((await screen.findByTestId("pbx-restriction")).textContent).toMatch(/Interdit : _08\.\s*· Koffi Yao/);
        fireEvent.click(screen.getByRole("button", { name: /Nouvelle restriction/ }));
        fireEvent.click(screen.getByRole("button", { name: "Pas d'appels internationaux" }));
        fireEvent.change(screen.getByLabelText(/Code de dérogation/), { target: { value: "4321" } });
        fireEvent.click(screen.getByRole("checkbox", { name: "Aya Diallo" }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Créer/ }));
        });
        expect(mocks.create).toHaveBeenCalledWith({
            body: { name: "Pas d'appels internationaux", mode: "deny", patterns: ["_00.", "_+X."], pin: "4321", user_ids: [2] },
        });
    });

    it("changes the extensions of a restriction and deletes it", async () => {
        render(<RestrictionsSection users={users} />);
        const row = await screen.findByTestId("pbx-restriction");
        fireEvent.click(within(row).getByRole("button", { name: /Postes/ }));
        const dialog = screen.getByRole("dialog");
        expect((within(dialog).getByRole("checkbox", { name: "Koffi Yao" }) as HTMLButtonElement).getAttribute("data-state")).toBe("checked");
        fireEvent.click(within(dialog).getByRole("checkbox", { name: "Koffi Yao" }));
        fireEvent.click(within(dialog).getByRole("checkbox", { name: "Aya Diallo" }));
        await act(async () => {
            fireEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
        });
        expect(mocks.users).toHaveBeenCalledWith({ path: { permission_id: 70 }, body: { user_ids: [2] } });
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: "Supprimer Accueil" }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { permission_id: 70 } });
    });
});

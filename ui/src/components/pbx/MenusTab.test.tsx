import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import type { DestinationSources } from "./DestinationPicker";
import { MenusTab } from "./MenusTab";
import type { PbxMenu } from "./types";

const mocks = vi.hoisted(() => ({
    create: vi.fn(),
    update: vi.fn(),
    publish: vi.fn(),
    remove: vi.fn(),
    preview: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    createMenuApiV1PbxMenusPost: mocks.create,
    updateMenuApiV1PbxMenusMenuIdPut: mocks.update,
    publishMenuApiV1PbxMenusMenuIdPublishPost: mocks.publish,
    deleteMenuApiV1PbxMenusMenuIdDelete: mocks.remove,
    previewPromptApiV1PbxPromptsPreviewPost: mocks.preview,
}));

const sources: DestinationSources = {
    queues: [{ id: 1, name: "Ventes", extensions: ["3001"], members: 2 }],
    users: [{ id: 3, uuid: "u-3", name: "Koffi Yao", extension: "1001", email: null, enabled: true }],
    voicemails: [{ id: 1, name: "Accueil", number: "1000" }],
    workflows: [{ id: 4, name: "Assistante IA" } as never],
    menus: [],
    aiEnabled: true,
};
const menu: PbxMenu = {
    id: 2,
    name: "Standard",
    pbx_ivr_id: 31,
    published_at: "2026-11-21T09:00:00Z",
    up_to_date: false,
    last_error: null,
    spec: {
        greeting_text: "Bienvenue.",
        menu_text: "",
        invalid_text: "Ce choix n'est pas valide.",
        timeout_seconds: 5,
        max_tries: 3,
        voice_workflow_id: null,
        fallback: { type: "ai", target_id: 4 },
        choices: [{ digit: "1", label: "Les ventes", type: "queue", target_id: 1 }],
    },
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.create.mockResolvedValue({ data: { ...menu, id: 9 } });
    mocks.update.mockResolvedValue({ data: menu });
    mocks.publish.mockResolvedValue({ data: menu });
    mocks.remove.mockResolvedValue({ data: null });
});

describe("MenusTab", () => {
    it("lists menus with their status and AI access", async () => {
        const onChanged = vi.fn();
        render(<MenusTab menus={[menu]} sources={sources} onChanged={onChanged} />);
        const card = screen.getByTestId("pbx-menu");
        expect(card.textContent).toContain("Modifié, à republier");
        expect(card.textContent).toContain("1 accès IA");
        expect(card.textContent).toContain("« Pour les ventes, tapez 1. »");
        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: /Publier/ }));
        });
        expect(mocks.publish).toHaveBeenCalledWith({ path: { menu_id: 2 } });
        expect(onChanged).toHaveBeenCalled();
        await act(async () => {
            fireEvent.click(within(card).getByRole("button", { name: "Supprimer Standard" }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { menu_id: 2 } });
    });

    it("designs a menu visually and publishes it", async () => {
        render(<MenusTab menus={[]} sources={sources} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Nouveau menu/ }));
        const save = screen.getByRole("button", { name: /Enregistrer et publier/ });
        expect(save).toHaveProperty("disabled", true);
        expect(screen.getByText("Donnez un nom au menu.")).toBeTruthy();

        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Accueil" } });
        fireEvent.change(screen.getByLabelText("Libellé du choix 1"), { target: { value: "Le service commercial" } });
        selectOption(screen.getByRole("combobox", { name: "Destination du choix 1 — type" }), "File d'attente");
        fireEvent.click(screen.getByRole("button", { name: /Ajouter un choix/ }));
        fireEvent.change(screen.getByLabelText("Libellé du choix 2"), { target: { value: "Notre assistante" } });
        selectOption(screen.getByRole("combobox", { name: "Destination du choix 2 — type" }), "Agent IA");
        selectOption(screen.getByRole("combobox", { name: "Touche du choix 2" }), "#");

        const flow = screen.getByTestId("menu-flow");
        expect(flow.textContent).toContain(
            "« Pour le service commercial, tapez 1. Pour notre assistante, tapez dièse. »",
        );
        expect(flow.textContent).toContain("Agent IA · Assistante IA");
        expect((screen.getByLabelText("Message du menu") as HTMLTextAreaElement).placeholder).toContain("tapez dièse");

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer et publier/ }));
        });
        const body = mocks.create.mock.calls[0][0].body;
        expect(body.name).toBe("Accueil");
        expect(body.spec.choices).toEqual([
            { digit: "1", label: "Le service commercial", type: "queue", target_id: 1 },
            { digit: "#", label: "Notre assistante", type: "ai", target_id: 4 },
        ]);
        expect(mocks.publish).toHaveBeenCalledWith({ path: { menu_id: 9 } });
    });

    it("plays a prompt in the organization's voice", async () => {
        const play = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal(
            "Audio",
            class {
                onended: (() => void) | null = null;
                play = play;
            },
        );
        URL.createObjectURL = vi.fn(() => "blob:x");
        mocks.preview.mockResolvedValue({ data: new Blob(["RIFF"], { type: "audio/wav" }) });
        render(<MenusTab menus={[menu]} sources={sources} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Modifier/ }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Écouter l'accueil" }));
        });
        expect(mocks.preview).toHaveBeenCalledWith({
            body: { text: "Bienvenue.", voice_workflow_id: null },
            parseAs: "blob",
        });
        expect(play).toHaveBeenCalled();
    });
});

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExtensionsTab } from "./ExtensionsTab";

const mocks = vi.hoisted(() => ({
    create: vi.fn(),
    remove: vi.fn(),
    reset: vi.fn(),
    preview: vi.fn(),
    run: vi.fn(),
    presence: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    createExtensionApiV1PbxExtensionsPost: mocks.create,
    deleteExtensionApiV1PbxExtensionsUserUuidDelete: mocks.remove,
    extensionPasswordResetApiV1PbxExtensionsPasswordResetPost: mocks.reset,
    previewImportApiV1PbxExtensionsImportPreviewPost: mocks.preview,
    runImportApiV1PbxExtensionsImportPost: mocks.run,
    readPresenceApiV1PbxPresenceGet: mocks.presence,
}));

const created = {
    uuid: "u-9", name: "Awa Diallo", extension: "1010", context: "default", line: "webrtc", agent_id: 12,
    credentials: { login: "awa@ivoire-immo.ci", login_password: "Pw-login-123", sip_username: "awa1234", sip_password: "Sip-secret-xyz", voicemail_pin: "482913" },
};
const users = [{ uuid: "u-1", name: "Koffi Yao", extension: "1001", email: "koffi@ivoire-immo.ci", enabled: true, login: "koffi@ivoire-immo.ci" }];

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.create.mockResolvedValue({ data: created });
    mocks.remove.mockResolvedValue({ data: undefined });
    mocks.reset.mockResolvedValue({ data: undefined });
    mocks.presence.mockResolvedValue({
        data: { live: true, extensions: { "1001": { state: "away", label: "Absent", status: "Déjeuner" } } },
    });
});

describe("extensions presence", () => {
    it("shows each extension's presence", async () => {
        render(<ExtensionsTab users={users} onChanged={vi.fn()} />);
        const badge = await screen.findByTestId("presence");
        expect(badge.textContent).toContain("Absent");
        expect(badge.textContent).toContain("Déjeuner");
    });
});

describe("extensions tab", () => {
    it("creates an extension and shows its credentials once", async () => {
        const onChanged = vi.fn();
        render(<ExtensionsTab users={users} onChanged={onChanged} />);
        fireEvent.click(screen.getByRole("button", { name: /Nouveau poste/ }));
        fireEvent.change(screen.getByLabelText("Prénom"), { target: { value: "Awa" } });
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Diallo" } });
        fireEvent.change(screen.getByLabelText("Numéro de poste"), { target: { value: "1010" } });
        fireEvent.click(screen.getByRole("switch", { name: "Agent du centre d'appels" }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Créer le poste/ }));
        });
        expect(mocks.create).toHaveBeenCalledWith({
            body: { firstname: "Awa", lastname: "Diallo", extension: "1010", email: null, line: "webrtc", voicemail: true, agent: true },
        });
        const row = await screen.findByTestId("credentials-row");
        expect(row.textContent).toContain("Pw-login-123");
        expect(row.textContent).toContain("Sip-secret-xyz");
        expect(screen.getByText(/ne seront plus affichés/)).toBeTruthy();
        expect(onChanged).toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: /J'ai enregistré les identifiants/ }));
        await waitFor(() => expect(screen.queryByTestId("credentials-row")).toBeNull());
    });

    it("sends a password link and deletes an extension", async () => {
        render(<ExtensionsTab users={users} onChanged={vi.fn()} />);
        const row = screen.getByTestId("pbx-user");
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: /Mot de passe/ }));
        });
        expect(mocks.reset).toHaveBeenCalledWith({ body: { login: "koffi@ivoire-immo.ci" } });
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: "Supprimer Koffi Yao" }));
        });
        expect(mocks.remove).toHaveBeenCalledWith({ path: { user_uuid: "u-1" } });
    });

    it("previews a CSV, imports the valid rows and reports the others", async () => {
        mocks.preview.mockResolvedValue({
            data: [
                { line: 2, firstname: "Awa", lastname: "Diallo", extension: "1010", email: null, type: "webrtc", voicemail: true, agent: true, errors: [] },
                { line: 3, firstname: "Koffi", lastname: "Yao", extension: "1001", email: null, type: "sip", voicemail: false, agent: false, errors: ["Le poste 1001 existe déjà"] },
            ],
        });
        mocks.run.mockResolvedValue({ data: { created: [created], failed: [{ line: 3 }], credentials_csv: "nom;poste\nAwa Diallo;1010\n" } });
        render(<ExtensionsTab users={users} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Importer \(CSV\)/ }));
        const file = new File(["prenom;nom;poste\nAwa;Diallo;1010\nKoffi;Yao;1001\n"], "postes.csv", { type: "text/csv" });
        await act(async () => {
            fireEvent.change(screen.getByTestId("csv-input"), { target: { files: [file] } });
        });
        await waitFor(() => expect(screen.getAllByTestId("import-row")).toHaveLength(2));
        expect(screen.getByText("postes.csv")).toBeTruthy();
        expect(screen.getByText("Le poste 1001 existe déjà")).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Créer 1 poste" }));
        });
        expect(mocks.run.mock.calls[0][0].body.content).toContain("Koffi;Yao;1001");
        expect(mocks.toast.error).toHaveBeenCalledWith("1 ligne(s) non importée(s) : corrigez-les et réimportez-les.");
        expect(await screen.findByTestId("credentials-row")).toBeTruthy();
    });
});

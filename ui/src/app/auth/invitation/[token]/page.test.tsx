import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InvitationPage from "./page";

const mocks = vi.hoisted(() => ({ read: vi.fn(), accept: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({ useParams: () => ({ token: "tok123" }) }));
vi.mock("@/components/auth/AuthShell", () => ({ AuthShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("@/client/sdk.gen", () => ({
    readInvitationApiV1AuthInvitationsTokenGet: mocks.read,
    acceptInvitationApiV1AuthInvitationsTokenAcceptPost: mocks.accept,
}));

const fetchMock = vi.fn().mockResolvedValue({ ok: true });

beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(window, "location", { value: { href: "" }, writable: true });
});
afterEach(() => vi.unstubAllGlobals());

const invitation = {
    kind: "company_owner",
    email: "fatou@diallo.example",
    name: "Fatou Diallo",
    target_name: "Boulangerie Diallo",
    existing_account: false,
    expires_at: "2026-12-01T00:00:00Z",
};

describe("Invitation page", () => {
    it("creates the account, opens the session and goes to the company", async () => {
        mocks.read.mockResolvedValue({ data: invitation });
        mocks.accept.mockResolvedValue({ data: { token: "jwt", user: { id: 7, organization_id: 42 } } });
        render(<InvitationPage />);
        expect(await screen.findByText("Rejoindre Boulangerie Diallo")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Choisissez un mot de passe"), { target: { value: "motdepasse-solide" } });
        fireEvent.change(screen.getByLabelText("Confirmez le mot de passe"), { target: { value: "autre-chose" } });
        expect(screen.getByText("Les deux mots de passe diffèrent.")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Confirmez le mot de passe"), { target: { value: "motdepasse-solide" } });
        fireEvent.click(screen.getByRole("button", { name: "Créer mon compte" }));
        await waitFor(() => expect(window.location.href).toBe("/after-sign-in"));
        expect(mocks.accept.mock.calls[0][0]).toEqual({
            path: { token: "tok123" },
            body: { password: "motdepasse-solide", name: "Fatou Diallo" },
        });
        expect(fetchMock).toHaveBeenCalledWith("/api/auth/session", expect.objectContaining({ method: "POST" }));
    });

    it("asks an existing account for its password and a reseller admin lands on the console", async () => {
        mocks.read.mockResolvedValue({ data: { ...invitation, kind: "reseller_admin", existing_account: true, target_name: "Acme" } });
        mocks.accept.mockResolvedValue({ data: { token: "jwt", user: { id: 7 } } });
        render(<InvitationPage />);
        expect(await screen.findByText(/Un compte existe déjà/)).toBeTruthy();
        expect(screen.queryByLabelText("Confirmez le mot de passe")).toBeNull();
        fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "ancien-mot-de-passe" } });
        fireEvent.click(screen.getByRole("button", { name: "Rejoindre" }));
        await waitFor(() => expect(window.location.href).toBe("/reseller"));
        expect(mocks.accept.mock.calls[0][0].body).toEqual({ password: "ancien-mot-de-passe", name: null });
    });

    it("explains a used or expired link", async () => {
        mocks.read.mockResolvedValue({ error: { detail: "Cette invitation a déjà servi" } });
        render(<InvitationPage />);
        expect(await screen.findByText("Cette invitation a déjà servi")).toBeTruthy();
        expect(screen.queryByRole("button")).toBeNull();
    });
});

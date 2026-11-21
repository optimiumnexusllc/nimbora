import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PasswordResetForm } from "./PasswordResetForm";

const mocks = vi.hoisted(() => ({ reset: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => mocks.params }));
vi.mock("@/client/sdk.gen", () => ({ resetPasswordApiV1PbxPasswordResetPost: mocks.reset }));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = new URLSearchParams("host=pbx.ivoire-immo.ci&token=tok-123456&user_uuid=u-1-uuid");
});

describe("PBX password reset page", () => {
    it("refuses an incomplete link", () => {
        mocks.params = new URLSearchParams("host=pbx.ivoire-immo.ci");
        render(<PasswordResetForm />);
        expect(screen.getByTestId("invalid-link")).toBeTruthy();
    });

    it("checks the password and sends the e-mail token", async () => {
        mocks.reset.mockResolvedValue({ data: undefined });
        render(<PasswordResetForm />);
        const submit = screen.getByRole("button", { name: /Enregistrer le mot de passe/ });
        fireEvent.change(screen.getByLabelText(/Mot de passe/), { target: { value: "court" } });
        expect(screen.getByText("Au moins 8 caractères.")).toBeTruthy();
        fireEvent.change(screen.getByLabelText(/Mot de passe/), { target: { value: "Nouveau-2026!" } });
        fireEvent.change(screen.getByLabelText("Confirmation"), { target: { value: "Autre-2026!" } });
        expect(submit).toHaveProperty("disabled", true);
        fireEvent.change(screen.getByLabelText("Confirmation"), { target: { value: "Nouveau-2026!" } });
        await act(async () => {
            fireEvent.click(submit);
        });
        expect(mocks.reset).toHaveBeenCalledWith({
            body: { host: "pbx.ivoire-immo.ci", token: "tok-123456", user_uuid: "u-1-uuid", password: "Nouveau-2026!" },
        });
        expect(screen.getByText("Mot de passe modifié")).toBeTruthy();
    });

    it("explains an expired link", async () => {
        mocks.reset.mockResolvedValue({ error: { detail: "Lien expiré ou déjà utilisé" } });
        render(<PasswordResetForm />);
        fireEvent.change(screen.getByLabelText(/Mot de passe/), { target: { value: "Nouveau-2026!" } });
        fireEvent.change(screen.getByLabelText("Confirmation"), { target: { value: "Nouveau-2026!" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer le mot de passe/ }));
        });
        expect(screen.getByText("Lien expiré ou déjà utilisé")).toBeTruthy();
    });
});

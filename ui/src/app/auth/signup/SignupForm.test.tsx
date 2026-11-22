import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "../login/LoginForm";
import { SignupForm } from "./SignupForm";

const mocks = vi.hoisted(() => ({ signup: vi.fn(), login: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: mocks.error } }));
vi.mock("@/client/sdk.gen", () => ({
    signupApiV1AuthSignupPost: mocks.signup,
    loginApiV1AuthLoginPost: mocks.login,
}));
vi.mock("@/components/auth/AuthShell", () => ({
    AuthShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const fill = (label: string, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });

beforeEach(() => vi.clearAllMocks());

describe("SignupForm", () => {
    it("speaks French and sends the name", async () => {
        mocks.signup.mockResolvedValue({ error: { detail: "Email already registered" } });
        render(<SignupForm signupEnabled />);
        expect(screen.getByRole("heading", { name: "Créer un compte" })).toBeTruthy();
        fill("Nom complet", "Awa Koné");
        fill("E-mail professionnel", "awa@ivoire-immo.ci");
        fill("Mot de passe", "Secret-2026");
        fill("Confirmer le mot de passe", "Secret-2026");
        fireEvent.click(screen.getByRole("button", { name: "Créer mon compte" }));
        await waitFor(() =>
            expect(mocks.error).toHaveBeenCalledWith("Un compte existe déjà avec cet e-mail. Connectez-vous."),
        );
        expect(mocks.signup.mock.calls[0][0].body).toEqual({
            email: "awa@ivoire-immo.ci",
            password: "Secret-2026",
            name: "Awa Koné",
        });
    });

    it("checks the passwords before calling the API", () => {
        render(<SignupForm signupEnabled />);
        fill("E-mail professionnel", "awa@ivoire-immo.ci");
        fill("Mot de passe", "Secret-2026");
        fill("Confirmer le mot de passe", "Secret-2027");
        fireEvent.submit(screen.getByRole("button", { name: "Créer mon compte" }).closest("form")!);
        expect(mocks.error).toHaveBeenCalledWith("Les deux mots de passe ne correspondent pas.");
        expect(mocks.signup).not.toHaveBeenCalled();
    });

    it("shows no form when the platform closed signups", () => {
        render(<SignupForm signupEnabled={false} />);
        expect(screen.getByTestId("signup-closed")).toBeTruthy();
        expect(screen.queryByLabelText("Mot de passe")).toBeNull();
        expect(screen.getByRole("link", { name: "Se connecter" }).getAttribute("href")).toBe("/auth/login");
    });
});

describe("LoginForm", () => {
    it("translates a refused login", async () => {
        mocks.login.mockResolvedValue({ error: { detail: "Invalid email or password" } });
        render(<LoginForm signupEnabled={false} />);
        fill("E-mail", "awa@ivoire-immo.ci");
        fill("Mot de passe", "mauvais");
        fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
        await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("E-mail ou mot de passe incorrect."));
        expect(screen.queryByText("Créer un compte")).toBeNull();
    });
});

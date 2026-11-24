import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResellerStripeCard } from "./ResellerStripeCard";

const mocks = vi.hoisted(() => ({ state: vi.fn(), onboarding: vi.fn(), dashboard: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    getStripeStateApiV1ResellerStripeGet: mocks.state,
    startStripeOnboardingApiV1ResellerStripeOnboardingPost: mocks.onboarding,
    openStripeDashboardApiV1ResellerStripeDashboardPost: mocks.dashboard,
}));

const assign = vi.fn();
beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "location", { value: { search: "", assign }, writable: true });
});

describe("ResellerStripeCard", () => {
    it("sends a reseller without an account to Stripe's onboarding", async () => {
        mocks.state.mockResolvedValue({ data: { connected: false, charges_enabled: false, details_submitted: false } });
        mocks.onboarding.mockResolvedValue({ data: { url: "https://connect.stripe.test/setup/abc" } });
        render(<ResellerStripeCard commissionPercent={20} />);
        expect(await screen.findByText("Non connecté")).toBeTruthy();
        expect(screen.getByText(/moins la commission de la plateforme \(20 %\)/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Tableau de bord/ })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Connecter mon compte Stripe" }));
        await waitFor(() => expect(assign).toHaveBeenCalledWith("https://connect.stripe.test/setup/abc"));
    });

    it("lets an unfinished account finish, and opens the dashboard", async () => {
        mocks.state.mockResolvedValue({ data: { connected: true, charges_enabled: false, details_submitted: true } });
        mocks.dashboard.mockResolvedValue({ data: { url: "https://connect.stripe.test/express/xyz" } });
        render(<ResellerStripeCard commissionPercent={17.5} />);
        expect(await screen.findByText("Inscription à terminer")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Terminer l'inscription Stripe" })).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Tableau de bord Stripe/ }));
        await waitFor(() => expect(assign).toHaveBeenCalledWith("https://connect.stripe.test/express/xyz"));
    });

    it("shows an active account without the onboarding button", async () => {
        mocks.state.mockResolvedValue({ data: { connected: true, charges_enabled: true, details_submitted: true } });
        render(<ResellerStripeCard commissionPercent={20} />);
        expect(await screen.findByText("Actif")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /inscription|Connecter/ })).toBeNull();
    });
});

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ResellerPage from "./page";

const mocks = vi.hoisted(() => ({
    me: vi.fn(),
    companies: vi.fn(),
    offers: vi.fn(),
    bases: vi.fn(),
    createCompany: vi.fn(),
    updateCompany: vi.fn(),
    invite: vi.fn(),
    createOffer: vi.fn(),
    updateOffer: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    getResellerApiV1ResellerGet: mocks.me,
    listCompaniesApiV1ResellerCompaniesGet: mocks.companies,
    listOffersApiV1ResellerPlansGet: mocks.offers,
    listBasePlansApiV1ResellerBasePlansGet: mocks.bases,
    createCompanyApiV1ResellerCompaniesPost: mocks.createCompany,
    updateCompanyApiV1ResellerCompaniesOrganizationIdPatch: mocks.updateCompany,
    inviteToCompanyApiV1ResellerCompaniesOrganizationIdInvitationsPost: mocks.invite,
    createOfferApiV1ResellerPlansPost: mocks.createOffer,
    updateOfferApiV1ResellerPlansCodePut: mocks.updateOffer,
}));

const offer = {
    code: "r1-essentiel-ab12",
    name: "Acme Essentiel",
    description: null,
    currency: "eur",
    monthly_price_cents: 12900,
    base_plan_code: "starter",
    included_minutes: 800,
    included_human_minutes: 1000,
    max_concurrent_calls: 3,
    max_agents: 3,
    max_human_seats: 2,
    max_campaigns: 2,
    features: { contact_center: true },
    is_public: false,
};
const company = {
    organization_id: 42,
    company_name: "Boulangerie Diallo",
    billing_email: "fatou@diallo.example",
    plan_code: offer.code,
    plan_name: offer.name,
    status: "trialing",
    trial_ends_at: null,
    created_at: null,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.me.mockResolvedValue({ data: { id: 1, name: "Acme Télécom", commission_percent: 20, stripe_ready: false, companies: 1 } });
    mocks.companies.mockResolvedValue({ data: [company] });
    mocks.offers.mockResolvedValue({ data: [offer] });
    mocks.bases.mockResolvedValue({ data: [{ ...offer, code: "starter", name: "Starter", base_plan_code: null, monthly_price_cents: 9900, included_minutes: 1000 }] });
});

describe("Reseller console", () => {
    it("shows its companies, its commission and the online payment state", async () => {
        render(<ResellerPage />);
        expect(await screen.findByText("Boulangerie Diallo")).toBeTruthy();
        expect(screen.getByText(/Console revendeur · Acme Télécom/)).toBeTruthy();
        expect(screen.getByText(/commission de la plateforme : 20 %/)).toBeTruthy();
        expect(screen.getByText(/paiement en ligne : à connecter/)).toBeTruthy();
    });

    it("suspends a company and hands out a new access link once", async () => {
        mocks.updateCompany.mockResolvedValue({ data: { ...company, status: "suspended" } });
        mocks.invite.mockResolvedValue({ data: { invitation_url: "https://app.test/auth/invitation/tok" } });
        render(<ResellerPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Suspendre" }));
        await waitFor(() => expect(mocks.updateCompany).toHaveBeenCalled());
        expect(mocks.updateCompany.mock.calls[0][0]).toEqual({ path: { organization_id: 42 }, body: { status: "suspended" } });

        fireEvent.click(screen.getByRole("button", { name: /Lien d'accès/ }));
        const dialog = await screen.findByRole("dialog");
        expect((within(dialog).getByLabelText("Lien d'invitation") as HTMLInputElement).value).toBe("https://app.test/auth/invitation/tok");
        expect(mocks.invite.mock.calls[0][0].body).toEqual({ email: "fatou@diallo.example" });
    });

    it("says so to someone who is not a reseller", async () => {
        mocks.me.mockResolvedValue({ error: { detail: "Réservé aux revendeurs" } });
        render(<ResellerPage />);
        expect(await screen.findByText("Réservé aux revendeurs")).toBeTruthy();
        expect(mocks.companies).not.toHaveBeenCalled();
    });
});

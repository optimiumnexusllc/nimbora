import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usageCsv } from "@/lib/enterpriseApi";

import { MonthlyUsageReport } from "./MonthlyUsageReport";

const mocks = vi.hoisted(() => ({ usage: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/enterpriseApi", async (original) => {
    const actual = await original<typeof import("@/lib/enterpriseApi")>();
    return { ...actual, enterpriseApi: { ...actual.enterpriseApi, adminMonthlyUsage: mocks.usage } };
});

const line = {
    organization_id: 7,
    company_name: "Ivoire Immo",
    billing_email: "compta@ivoire-immo.ci",
    plan_code: "business",
    currency: "eur",
    ai_minutes: 5120.5,
    ai_included_minutes: 5000,
    ai_overage_minutes: 120.5,
    ai_overage_cents: 1085,
    human_minutes: 9800,
    human_included_minutes: 10000,
    human_overage_minutes: 0,
    human_overage_cents: 0,
    total_overage_cents: 1085,
};

beforeEach(() => vi.clearAllMocks());

describe("MonthlyUsageReport", () => {
    it("lists AI and human minutes of each company with the overage", async () => {
        mocks.usage.mockResolvedValue({ month: "2026-11", lines: [line] });
        render(<MonthlyUsageReport />);
        await waitFor(() => expect(screen.getByText("Ivoire Immo")).toBeTruthy());
        const report = (screen.getByTestId("monthly-usage").textContent ?? "").replace(/\s/g, " ");
        expect(report).toContain("5 120,5");
        expect(report).toContain("9 800");
        expect(report).toContain("10,85");

        fireEvent.change(screen.getByLabelText("Mois"), { target: { value: "2026-10" } });
        fireEvent.click(screen.getByRole("button", { name: /Afficher/ }));
        await waitFor(() => expect(mocks.usage).toHaveBeenLastCalledWith("2026-10"));
    });

    it("exports a CSV that Excel opens", () => {
        const csv = usageCsv([{ ...line, company_name: 'Immo "Plateau"; Abidjan' }]);
        const [header, row] = csv.trim().split("\n");
        expect(header.split(";")[0]).toBe("organization_id");
        expect(header).toContain("human_minutes");
        expect(row).toContain('"Immo ""Plateau""; Abidjan"');
    });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HumanMinutes } from "./HumanMinutes";

const base = {
    platform_name: "NIMBORA",
    organization_id: 1,
    plan_code: "business",
    plan_name: "Business",
    status: "active",
    period_start: "2026-11-01T00:00:00Z",
    period_end: "2026-12-01T00:00:00Z",
    trial_ends_at: null,
    used_minutes: 10,
    included_minutes: 5000,
    remaining_minutes: 4990,
    overage_minutes: 0,
    estimated_overage_cents: 0,
    limits: {},
    features: {},
    usable: true,
    blocked_reason: null,
    can_manage_billing: false,
} as const;

describe("HumanMinutes", () => {
    it("shows the human minutes of the period and their overage", () => {
        render(
            <HumanMinutes
                subscription={{
                    ...base,
                    human_used_minutes: 10250,
                    human_included_minutes: 10000,
                    human_overage_minutes: 250,
                    estimated_human_overage_cents: 500,
                }}
            />,
        );
        const block = (screen.getByTestId("human-minutes").textContent ?? "").replace(/\s/g, " ");
        expect(block).toContain("10 250 / 10 000");
        expect(block).toContain("Dépassement : 250 min");
        expect(block).toContain("5,00");
    });

    it("is hidden for a company without human calls nor allowance", () => {
        const { container } = render(<HumanMinutes subscription={{ ...base }} />);
        expect(container.innerHTML).toBe("");
    });
});

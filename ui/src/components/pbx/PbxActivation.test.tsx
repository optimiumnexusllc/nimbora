import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PbxActivation, SeatsBadge } from "./PbxActivation";

const mocks = vi.hoisted(() => ({ provision: vi.fn(), toastError: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: mocks.toastError } }));
vi.mock("@/client/sdk.gen", () => ({ provisionApiV1PbxProvisionPost: mocks.provision }));

const access = (over: Record<string, unknown> = {}) =>
    ({
        shared: true,
        dedicated: true,
        shared_available: true,
        seats_limit: 15,
        seats_used: null,
        plan_name: "Business",
        connected: false,
        managed: false,
        ...over,
    }) as never;

beforeEach(() => vi.clearAllMocks());

describe("PbxActivation", () => {
    it("activates the platform PBX in one click", async () => {
        const connection = { configured: true, managed: true };
        mocks.provision.mockResolvedValue({ data: connection });
        const onActivated = vi.fn();
        render(<PbxActivation access={access()} pbxName="NIMBORA Voice" onActivated={onActivated} onConnectOwn={vi.fn()} />);

        expect(screen.getByText("NIMBORA Voice de la plateforme")).toBeTruthy();
        expect(screen.getByText(/15 postes humains/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Activer la téléphonie/ }));
        await waitFor(() => expect(onActivated).toHaveBeenCalledWith(connection));
    });

    it("shows the error when activation fails", async () => {
        mocks.provision.mockResolvedValue({ error: { detail: "Votre offre ne comprend pas la téléphonie" } });
        const onActivated = vi.fn();
        render(<PbxActivation access={access()} pbxName="PBX" onActivated={onActivated} onConnectOwn={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Activer la téléphonie/ }));
        await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith("Votre offre ne comprend pas la téléphonie"));
        expect(onActivated).not.toHaveBeenCalled();
    });

    it("offers only the own PBX when the platform has none", () => {
        const onConnectOwn = vi.fn();
        render(<PbxActivation access={access({ shared_available: false })} pbxName="PBX" onActivated={vi.fn()} onConnectOwn={onConnectOwn} />);
        expect(screen.queryByTestId("pbx-activate-shared")).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: /Connecter mon PBX/ }));
        expect(onConnectOwn).toHaveBeenCalled();
    });

    it("offers only the platform PBX when the plan excludes an own one", () => {
        render(<PbxActivation access={access({ dedicated: false })} pbxName="PBX" onActivated={vi.fn()} onConnectOwn={vi.fn()} />);
        expect(screen.getByTestId("pbx-activate-shared")).toBeTruthy();
        expect(screen.queryByTestId("pbx-connect-own")).toBeNull();
    });

    it("points to the plans when telephony is not included", () => {
        render(
            <PbxActivation access={access({ shared: false, dedicated: false })} pbxName="PBX" onActivated={vi.fn()} onConnectOwn={vi.fn()} />,
        );
        expect(screen.getByTestId("pbx-not-in-plan")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Voir les offres" }).getAttribute("href")).toBe("/subscription");
    });
});

describe("SeatsBadge", () => {
    it("shows the seats used against the plan", () => {
        render(<SeatsBadge access={access({ seats_used: 4, seats_limit: 15 })} />);
        expect(screen.getByTestId("pbx-seats").textContent).toContain("Postes 4 / 15");
    });

    it("is hidden without a limit", () => {
        const { container } = render(<SeatsBadge access={access({ seats_limit: null, seats_used: 3 })} />);
        expect(container.innerHTML).toBe("");
    });
});

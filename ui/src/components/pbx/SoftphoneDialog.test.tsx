import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftphoneDialog } from "./SoftphoneDialog";

const mocks = vi.hoisted(() => ({ create: vi.fn(), qr: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("qrcode", () => ({ default: { toDataURL: mocks.qr } }));
vi.mock("@/client/sdk.gen", () => ({ createSoftphoneActivationApiV1PbxExtensionsUserUuidSoftphonePost: mocks.create }));

const user = { id: 1, uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true };

beforeEach(() => {
    vi.clearAllMocks();
    mocks.qr.mockResolvedValue("data:image/png;base64,QR");
    mocks.create.mockResolvedValue({
        data: {
            code: "ABCD-2345",
            expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
            server: "https://api.ivoire-immo.ci",
            link: "nimbora-softphone://activate?server=https%3A%2F%2Fapi.ivoire-immo.ci&code=ABCD2345",
            display_name: "Koffi Yao",
            extension: "1001",
        },
    });
});

describe("SoftphoneDialog", () => {
    it("shows the one-time code, its QR link and where to download the app", async () => {
        Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
        render(<SoftphoneDialog user={user} onClose={vi.fn()} />);
        expect((await screen.findByTestId("softphone-code")).textContent).toBe("ABCD-2345");
        expect(mocks.create).toHaveBeenCalledWith({ path: { user_uuid: "u-1" } });
        expect(mocks.qr).toHaveBeenCalledWith(expect.stringContaining("nimbora-softphone://activate?"), expect.any(Object));
        expect((screen.getByAltText("QR code d'activation") as HTMLImageElement).src).toBe("data:image/png;base64,QR");
        expect(screen.getByText(/Valable 1[45] min/)).toBeTruthy();
        for (const platform of ["Windows", "macOS", "Linux", "Android", "iPhone / iPad", "Navigateur"]) expect(screen.getByText(platform)).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Copier le code" }));
        });
        expect(navigator.clipboard.writeText).toHaveBeenCalledWith("ABCD-2345");
    });

    it("explains why a desk-phone line cannot pair", async () => {
        mocks.create.mockResolvedValue({ error: { detail: "Ce poste n'a pas de ligne navigateur (WebRTC)" } });
        render(<SoftphoneDialog user={user} onClose={vi.fn()} />);
        expect((await screen.findByTestId("softphone-error")).textContent).toContain("WebRTC");
    });
});

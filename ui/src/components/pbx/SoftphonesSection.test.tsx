import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftphonesSection } from "./SoftphonesSection";

const mocks = vi.hoisted(() => ({ list: vi.fn(), settings: vi.fn(), save: vi.fn(), revoke: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    listSoftphoneDevicesApiV1PbxSoftphoneDevicesGet: mocks.list,
    readSoftphoneSettingsApiV1PbxSoftphoneSettingsGet: mocks.settings,
    saveSoftphoneSettingsApiV1PbxSoftphoneSettingsPut: mocks.save,
    revokeSoftphoneDeviceApiV1PbxSoftphoneDevicesDeviceIdDelete: mocks.revoke,
}));

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.list.mockResolvedValue({
        data: [{ id: 3, name: "iPhone de Koffi", platform: "ios", app_version: "1.0.0", pbx_user_uuid: "u-1", extension_name: "Koffi Yao (1001)", last_seen_at: "2026-11-21T09:00:00Z", created_at: null }],
    });
    mocks.settings.mockResolvedValue({ data: { wss_url: "wss://pbx.example/api/asterisk/ws", sip_domain: "pbx.example", overrides: {} } });
    mocks.save.mockResolvedValue({ data: {} });
    mocks.revoke.mockResolvedValue({ data: null });
});

describe("SoftphonesSection", () => {
    it("lists paired devices, revokes one and saves connection overrides", async () => {
        render(<SoftphonesSection />);
        const row = await screen.findByTestId("softphone-device");
        expect(row.textContent).toContain("iPhone / iPad");
        expect(row.textContent).toContain("Koffi Yao (1001)");
        await act(async () => {
            fireEvent.click(within(row).getByRole("button", { name: /Révoquer/ }));
        });
        expect(mocks.revoke).toHaveBeenCalledWith({ path: { device_id: 3 } });
        expect(screen.getByTestId("softphone-settings").textContent).toContain("wss://pbx.example/api/asterisk/ws");
        fireEvent.change(screen.getByLabelText("WebSocket sécurisé"), { target: { value: "wss://voix.example/ws" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        expect(mocks.save).toHaveBeenCalledWith({ body: { wss_url: "wss://voix.example/ws", sip_domain: "" } });
    });
});

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { SoftphoneApi } from "./lib/api";

const phones = vi.hoisted(() => ({ created: 0 }));

vi.mock("./lib/phone", async (original) => {
    const actual = await original<typeof import("./lib/phone")>();
    class StubPhone {
        constructor() {
            phones.created += 1;
        }
        state = { registration: "registered", error: null, call: null };
        onIncoming = null;
        subscribe(listener: (s: unknown) => void) {
            listener(this.state);
            return () => undefined;
        }
        start = vi.fn();
        stop = vi.fn();
        call = vi.fn();
    }
    return { ...actual, Phone: StubPhone };
});

const config = {
    brand: { name: "NIMBORA", pbx_name: "NIMBORA Voice" },
    device: { id: 1, name: "PC", platform: "windows" },
    account: { display_name: "Koffi Yao", extension: "1001", username: "k", password: "p", wss_url: "wss://x", sip_domain: "x" },
    ice_servers: [],
    features: { voicemail_code: "*98", transfer: true, dnd: true },
};

function fakeApi() {
    const api = new SoftphoneApi("https://api.example", null, vi.fn());
    Object.assign(api, {
        activate: vi.fn().mockResolvedValue({ token: "nsp_new", config }),
        config: vi.fn().mockResolvedValue(config),
        history: vi.fn().mockResolvedValue([{ id: 1, start: null, direction: "incoming", answered: false, duration: 0, number: "+2250700112233", name: "Awa" }]),
        directory: vi.fn().mockResolvedValue({ people: [{ name: "Aya Diallo", extension: "1002", me: false }], services: [] }),
        status: vi.fn().mockResolvedValue({ dnd: false, forward: { enabled: false, destination: "" } }),
        saveStatus: vi.fn().mockResolvedValue({ dnd: true, forward: { enabled: false, destination: "" } }),
        signOut: vi.fn().mockResolvedValue(undefined),
    });
    return api;
}

beforeEach(() => {
    localStorage.clear();
    phones.created = 0;
});

afterEach(() => cleanup());

describe("App", () => {
    it("pairs with a code, then shows the phone with recents and contacts", async () => {
        const api = fakeApi();
        render(<App makeApi={() => api} />);
        fireEvent.change(await screen.findByPlaceholderText("nimbora.votre-entreprise.com"), { target: { value: "api.example" } });
        fireEvent.change(screen.getByPlaceholderText("ABCD-2345"), { target: { value: "abcd2345" } });
        expect((screen.getByPlaceholderText("ABCD-2345") as HTMLInputElement).value).toBe("ABCD-2345");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Activer/ }));
        });
        expect(api.activate).toHaveBeenCalledWith("ABCD2345", expect.any(String), expect.any(String));
        expect(JSON.parse(localStorage.getItem("nimbora-softphone")!)).toMatchObject({ server: "https://api.example", token: "nsp_new" });
        expect(await screen.findByText("Koffi Yao")).toBeTruthy();
        expect(screen.getByTestId("registration").textContent).toContain("Disponible");

        fireEvent.click(screen.getByRole("button", { name: /Récents/ }));
        expect((await screen.findByTestId("recent")).textContent).toContain("Manqué");
        fireEvent.click(screen.getByRole("button", { name: /Contacts/ }));
        expect((await screen.findByTestId("contact")).textContent).toContain("Aya Diallo");
        fireEvent.click(screen.getByRole("button", { name: /Réglages/ }));
        await act(async () => {
            fireEvent.click(screen.getByRole("switch", { name: "Ne pas déranger" }));
        });
        expect(api.saveStatus).toHaveBeenCalledWith(true, false, "");
        expect(screen.getByTestId("registration").textContent).toContain("Ne pas déranger");
    });

    it("builds the SIP agent once, even across re-renders", async () => {
        localStorage.setItem("nimbora-softphone", JSON.stringify({ server: "https://api.example", token: "nsp_old", deviceName: "PC" }));
        const api = fakeApi();
        const { rerender } = render(<App makeApi={() => api} />);
        expect(await screen.findByText("Koffi Yao")).toBeTruthy();
        rerender(<App makeApi={() => api} />);
        fireEvent.click(screen.getByRole("button", { name: /Récents/ }));
        await screen.findByTestId("recent");
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50));
        });
        expect(api.config).toHaveBeenCalledTimes(1);
        expect(phones.created).toBe(1);
    });

    it("starts from a saved pairing and forgets a revoked device", async () => {
        localStorage.setItem("nimbora-softphone", JSON.stringify({ server: "https://api.example", token: "nsp_old", deviceName: "PC" }));
        const api = fakeApi();
        render(<App makeApi={() => api} />);
        expect(await screen.findByText("Koffi Yao")).toBeTruthy();

        const revoked = fakeApi();
        const { ApiError } = await import("./lib/api");
        (revoked.config as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError("Appareil non reconnu ou révoqué", 401));
        localStorage.setItem("nimbora-softphone", JSON.stringify({ server: "https://api.example", token: "nsp_old", deviceName: "PC" }));
        render(<App makeApi={() => revoked} />);
        expect(await screen.findByRole("button", { name: /Activer/ })).toBeTruthy();
        expect(localStorage.getItem("nimbora-softphone")).toBeNull();
    });
});

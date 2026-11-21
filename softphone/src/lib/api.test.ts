import { describe, expect, it, vi } from "vitest";

import { ApiError, forget, loadSaved, save, SoftphoneApi } from "./api";

const json = (status: number, body: unknown) =>
    new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("SoftphoneApi", () => {
    it("pairs, then authenticates every call with the device token", async () => {
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce(json(200, { token: "nsp_abc", config: { brand: { name: "NIMBORA" } } }))
            .mockResolvedValueOnce(json(200, { dnd: true, forward: { enabled: false, destination: "" } }));
        const api = new SoftphoneApi("https://api.example", null, fetcher);
        const paired = await api.activate("ABCD2345", "PC", "windows");
        expect(paired.token).toBe("nsp_abc");
        const [url, init] = fetcher.mock.calls[0];
        expect(url).toBe("https://api.example/api/v1/softphone/activate");
        expect(JSON.parse(init.body)).toMatchObject({ code: "ABCD2345", device_name: "PC", platform: "windows" });
        expect(init.headers.Authorization).toBeUndefined();
        await api.saveStatus(true, false, "");
        expect(fetcher.mock.calls[1][1].headers.Authorization).toBe("Bearer nsp_abc");
        expect(fetcher.mock.calls[1][1].method).toBe("PUT");
    });

    it("turns errors into readable messages", async () => {
        const api = new SoftphoneApi("https://api.example", "nsp_x", vi.fn().mockResolvedValue(json(401, { detail: "Appareil non reconnu ou révoqué" })));
        await expect(api.config()).rejects.toEqual(new ApiError("Appareil non reconnu ou révoqué", 401));
        const offline = new SoftphoneApi("https://api.example", "nsp_x", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
        await expect(offline.history()).rejects.toMatchObject({ status: 0 });
        const validation = new SoftphoneApi("https://x", null, vi.fn().mockResolvedValue(json(422, { detail: [{ msg: "Field required" }] })));
        await expect(validation.activate("x", "y", "web")).rejects.toThrow("Field required");
    });

    it("stores only the server and the device token", () => {
        const store = new Map<string, string>();
        const storage = {
            getItem: (k: string) => store.get(k) ?? null,
            setItem: (k: string, v: string) => void store.set(k, v),
            removeItem: (k: string) => void store.delete(k),
        } as unknown as Storage;
        expect(loadSaved(storage)).toBeNull();
        save({ server: "https://api.example", token: "nsp_abc", deviceName: "PC" }, storage);
        expect(loadSaved(storage)).toEqual({ server: "https://api.example", token: "nsp_abc", deviceName: "PC" });
        expect([...store.values()].join()).not.toContain("password");
        forget(storage);
        expect(loadSaved(storage)).toBeNull();
    });
});

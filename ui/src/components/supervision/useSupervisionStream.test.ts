import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { supervisionSocketUrl, useSupervisionStream } from "./useSupervisionStream";

const mocks = vi.hoisted(() => ({ snapshot: vi.fn(), live: vi.fn() }));
vi.mock("@/client/sdk.gen", () => ({
    snapshotApiV1SupervisionGet: mocks.snapshot,
    readLiveApiV1PbxSupervisionLiveGet: mocks.live,
}));
vi.mock("@/client/client.gen", () => ({ client: { getConfig: () => ({ baseUrl: "https://api.example" }) } }));

class FakeSocket {
    static instances: FakeSocket[] = [];
    static OPEN = 1;
    readyState = 0;
    sent: string[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    constructor(public url: string) {
        FakeSocket.instances.push(this);
    }
    send(data: string) {
        this.sent.push(data);
    }
    close() {
        this.readyState = 3;
    }
    open() {
        this.readyState = 1;
        this.onopen?.();
    }
    push(message: unknown) {
        this.onmessage?.({ data: JSON.stringify(message) });
    }
    fail() {
        this.readyState = 3;
        this.onclose?.();
    }
}

beforeEach(() => {
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    mocks.snapshot.mockResolvedValue({ data: { ai_calls: [], kpis: {} } });
    mocks.live.mockResolvedValue({ error: { detail: "Aucun PBX" }, response: { status: 404 } });
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("useSupervisionStream", () => {
    it("builds the socket URL from the API base and the token", () => {
        expect(supervisionSocketUrl("a b")).toBe("wss://api.example/api/v1/supervision/stream?token=a%20b");
    });

    it("receives the AI and PBX sides pushed by the server, and asks for refreshes", async () => {
        const { result } = renderHook(() =>
            useSupervisionStream({ enabled: true, getAccessToken: async () => "jwt" }),
        );
        await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
        const socket = FakeSocket.instances[0];
        expect(socket.url).toContain("token=jwt");
        act(() => socket.open());
        expect(result.current.mode).toBe("live");

        act(() => socket.push({ type: "ai", data: { ai_calls: [{ run_id: 1 }], kpis: {} } }));
        act(() => socket.push({ type: "pbx", data: null }));
        act(() => socket.push({ type: "ping" }));
        expect(result.current.ai?.ai_calls).toHaveLength(1);
        expect(result.current.pbx).toBeNull();
        expect(result.current.receivedAt.ai).toBeGreaterThan(0);
        expect(result.current.receivedAt.pbx).toBeGreaterThan(0);

        act(() => result.current.refresh());
        expect(socket.sent).toEqual(['{"type":"refresh"}']);
        expect(mocks.snapshot).not.toHaveBeenCalled(); // no polling while live
    });

    it("reconnects, then falls back to polling when the socket keeps failing", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const { result } = renderHook(() =>
            useSupervisionStream({ enabled: true, getAccessToken: async () => "jwt" }),
        );
        for (let attempt = 1; attempt <= 3; attempt += 1) {
            await waitFor(() => expect(FakeSocket.instances).toHaveLength(attempt));
            act(() => FakeSocket.instances[attempt - 1].fail());
            await act(async () => {
                await vi.advanceTimersByTimeAsync(20000);
            });
        }
        await waitFor(() => expect(result.current.mode).toBe("polling"));
        await waitFor(() => expect(result.current.ai).not.toBeNull());
        expect(result.current.pbx).toBeNull(); // 404: no PBX connected
        expect(FakeSocket.instances).toHaveLength(3);
    });

    it("polls straight away without a token", async () => {
        const { result } = renderHook(() =>
            useSupervisionStream({ enabled: true, getAccessToken: async () => null }),
        );
        await waitFor(() => expect(result.current.mode).toBe("polling"));
        expect(FakeSocket.instances).toHaveLength(0);
    });
});

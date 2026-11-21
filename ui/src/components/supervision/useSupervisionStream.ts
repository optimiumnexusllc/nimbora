"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { readLiveApiV1PbxSupervisionLiveGet, snapshotApiV1SupervisionGet } from "@/client/sdk.gen";
import type { SupervisionSnapshot } from "@/client/types.gen";
import { resolveBrowserBackendUrl } from "@/lib/apiClient";

import type { PbxLive } from "./types";

/** "live": pushed by the server; "polling": fallback every few seconds. */
export type StreamMode = "connecting" | "live" | "polling";

const POLL_MS = 5000;
const MAX_SOCKET_FAILURES = 3;

export function supervisionSocketUrl(token: string): string {
    const base = client.getConfig().baseUrl || resolveBrowserBackendUrl();
    return `${base.replace(/^http/, "ws")}/api/v1/supervision/stream?token=${encodeURIComponent(token)}`;
}

/**
 * Live supervision: one WebSocket pushes the AI side and the PBX side as
 * they change. If the socket keeps failing (proxy without WebSocket, old
 * server), the console polls both endpoints instead.
 */
export function useSupervisionStream({
    enabled,
    getAccessToken,
}: {
    enabled: boolean;
    getAccessToken: () => Promise<string | null | undefined>;
}) {
    const [ai, setAi] = useState<SupervisionSnapshot | null>(null);
    const [pbx, setPbx] = useState<PbxLive | null | undefined>(undefined);
    const [mode, setMode] = useState<StreamMode>("connecting");
    // When each side was last received: the console's clocks run from there.
    const [receivedAt, setReceivedAt] = useState<{ ai: number; pbx: number }>({ ai: 0, pbx: 0 });
    const socketRef = useRef<WebSocket | null>(null);
    // A ref, not a dependency: a new token getter must not reopen the socket.
    const tokenRef = useRef(getAccessToken);
    tokenRef.current = getAccessToken;
    const failures = useRef(0);
    const stopped = useRef(false);

    const poll = useCallback(async () => {
        const [snapshot, live] = await Promise.all([
            snapshotApiV1SupervisionGet(),
            readLiveApiV1PbxSupervisionLiveGet(),
        ]);
        if (!snapshot.error && snapshot.data) setAi(snapshot.data);
        if (live.response?.status === 404) setPbx(null);
        else if (!live.error && live.data) setPbx(live.data as unknown as PbxLive);
        else if (live.error) setPbx({ unavailable: "PBX injoignable" } as PbxLive);
        const now = Date.now();
        setReceivedAt({ ai: now, pbx: now });
    }, []);

    useEffect(() => {
        if (!enabled) return;
        stopped.current = false;
        let pollTimer: number | undefined;
        let retryTimer: number | undefined;

        const startPolling = () => {
            setMode("polling");
            void poll();
            pollTimer = window.setInterval(() => void poll(), POLL_MS);
        };

        const connect = async () => {
            const token = await tokenRef.current();
            if (stopped.current) return;
            if (!token || typeof WebSocket === "undefined") {
                startPolling();
                return;
            }
            let opened = false;
            const socket = new WebSocket(supervisionSocketUrl(token));
            socketRef.current = socket;
            socket.onopen = () => {
                opened = true;
                failures.current = 0;
                setMode("live");
            };
            socket.onmessage = (event) => {
                let message: { type?: string; data?: unknown };
                try {
                    message = JSON.parse(String(event.data));
                } catch {
                    return;
                }
                const now = Date.now();
                if (message.type === "ai") {
                    setAi(message.data as SupervisionSnapshot);
                    setReceivedAt((at) => ({ ...at, ai: now }));
                } else if (message.type === "pbx") {
                    setPbx((message.data as PbxLive | null) ?? null);
                    setReceivedAt((at) => ({ ...at, pbx: now }));
                }
            };
            socket.onclose = () => {
                socketRef.current = null;
                if (stopped.current) return;
                if (!opened) failures.current += 1;
                if (failures.current >= MAX_SOCKET_FAILURES) {
                    startPolling();
                    return;
                }
                setMode("connecting");
                const delay = Math.min(15000, 1000 * 2 ** failures.current);
                retryTimer = window.setTimeout(() => void connect(), delay);
            };
        };

        void connect();
        return () => {
            stopped.current = true;
            window.clearInterval(pollTimer);
            window.clearTimeout(retryTimer);
            socketRef.current?.close();
            socketRef.current = null;
        };
    }, [enabled, poll]);

    const refresh = useCallback(() => {
        const socket = socketRef.current;
        if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "refresh" }));
        else void poll();
    }, [poll]);

    return { ai, pbx, mode, receivedAt, refresh };
}

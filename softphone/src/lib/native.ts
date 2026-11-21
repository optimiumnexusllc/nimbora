/**
 * What changes between the browser and the native shells (Tauri on Windows,
 * macOS, Linux, Android, iOS): notifications, pairing links, ringtone.
 * Everything degrades gracefully to the web APIs.
 */

type TauriGlobal = {
    event?: { listen: (event: string, cb: (e: { payload: unknown }) => void) => Promise<() => void> };
    core?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
};

export function tauri(): TauriGlobal | null {
    return (globalThis as unknown as { __TAURI__?: TauriGlobal }).__TAURI__ ?? null;
}

export function isNative(): boolean {
    return tauri() !== null;
}

/** Pairing links opened while the app runs (and the one that launched it). */
export async function onPairingLink(handler: (url: string) => void): Promise<() => void> {
    const fromLocation = new URLSearchParams(globalThis.location?.search ?? "").get("link");
    if (fromLocation) handler(fromLocation);
    const t = tauri();
    if (!t?.event) return () => undefined;
    try {
        const current = (await t.core?.invoke("plugin:deep-link|get_current")) as string[] | null;
        if (current?.[0]) handler(current[0]);
    } catch {
        // Deep links unavailable on this platform.
    }
    return t.event.listen("deep-link://new-url", (e) => {
        const urls = e.payload as string[] | undefined;
        if (urls?.[0]) handler(urls[0]);
    });
}

export async function notify(title: string, body: string): Promise<void> {
    if (typeof Notification === "undefined") return;
    try {
        if (Notification.permission === "default") await Notification.requestPermission();
        if (Notification.permission === "granted") new Notification(title, { body, tag: "nimbora-call", requireInteraction: true });
    } catch {
        // Notifications blocked: the in-app ring still plays.
    }
}

/** A classic two-tone ring, generated (no audio file to ship or license). */
export class Ringtone {
    private context: AudioContext | null = null;
    private timer: ReturnType<typeof setInterval> | null = null;

    start() {
        if (this.timer || typeof AudioContext === "undefined") return;
        try {
            this.context = new AudioContext();
        } catch {
            return;
        }
        const ring = () => {
            const ctx = this.context;
            if (!ctx) return;
            const now = ctx.currentTime;
            for (const [offset, frequency] of [
                [0, 440],
                [0, 480],
                [0.45, 440],
                [0.45, 480],
            ] as const) {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.frequency.value = frequency;
                gain.gain.setValueAtTime(0.08, now + offset);
                gain.gain.setValueAtTime(0, now + offset + 0.4);
                osc.connect(gain).connect(ctx.destination);
                osc.start(now + offset);
                osc.stop(now + offset + 0.4);
            }
        };
        ring();
        this.timer = setInterval(ring, 3000);
    }

    stop() {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        void this.context?.close().catch(() => undefined);
        this.context = null;
    }
}

export function registerServiceWorker() {
    if (isNative() || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    if (globalThis.location?.protocol !== "https:") return;
    void navigator.serviceWorker.register("./sw.js").catch(() => undefined);
}

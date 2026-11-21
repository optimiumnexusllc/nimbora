/** NIMBORA Softphone API client (device-token authentication). */

import type { Platform } from "./format";

export const APP_VERSION = "1.1.0";

export type IceServer = { urls: string[] | string; username?: string; credential?: string };
export type SoftphoneConfig = {
    brand: { name: string; pbx_name: string; support_email?: string };
    device: { id: number; name: string; platform: Platform };
    account: {
        display_name: string;
        extension: string | null;
        username: string;
        password: string;
        wss_url: string;
        sip_domain: string;
    };
    ice_servers: IceServer[];
    features: { voicemail_code: string; transfer: boolean; dnd: boolean };
};
export type RecentCall = {
    id: number;
    start: string | null;
    direction: "incoming" | "outgoing";
    answered: boolean;
    duration: number;
    number: string | null;
    name: string | null;
};
export type Directory = {
    people: { name: string; extension: string; me: boolean }[];
    services: { name: string; extension: string; kind: "group" | "queue" }[];
};
export type Status = { dnd: boolean; forward: { enabled: boolean; destination: string } };
/** What the AI agent knew when it handed this caller to a human. */
export type HandoffCard = {
    id: string;
    caller_number: string | null;
    customer_name: string | null;
    reason: string | null;
    summary: string | null;
    sentiment: "positive" | "neutral" | "frustrated" | "angry" | null;
    next_step: string | null;
    summary_status: string;
    collected_data: Record<string, unknown>;
    transcript: { speaker: string; text: string }[];
};

export class ApiError extends Error {
    constructor(
        message: string,
        public status: number,
    ) {
        super(message);
    }
}

type Fetch = typeof fetch;

function detail(body: unknown, fallback: string): string {
    if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        if (typeof d === "string") return d;
        if (Array.isArray(d) && d[0] && typeof d[0] === "object" && "msg" in d[0]) return String((d[0] as { msg: unknown }).msg);
    }
    return fallback;
}

export class SoftphoneApi {
    constructor(
        public server: string,
        private token: string | null = null,
        private fetcher: Fetch = (...args) => fetch(...args),
    ) {}

    private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
        const headers: Record<string, string> = { Accept: "application/json", "X-App-Version": APP_VERSION };
        if (body !== undefined) headers["Content-Type"] = "application/json";
        if (this.token) headers.Authorization = `Bearer ${this.token}`;
        let response: Response;
        try {
            response = await this.fetcher(`${this.server}/api/v1/softphone${path}`, {
                method,
                headers,
                body: body === undefined ? undefined : JSON.stringify(body),
            });
        } catch {
            throw new ApiError("Serveur injoignable : vérifiez l'adresse et votre connexion.", 0);
        }
        if (response.status === 204) return undefined as T;
        let payload: unknown = null;
        try {
            payload = await response.json();
        } catch {
            payload = null;
        }
        if (!response.ok) throw new ApiError(detail(payload, `Erreur ${response.status}`), response.status);
        return payload as T;
    }

    async activate(code: string, deviceName: string, platform: Platform) {
        const result = await this.call<{ token: string; config: SoftphoneConfig }>("POST", "/activate", {
            code,
            device_name: deviceName,
            platform,
            app_version: APP_VERSION,
        });
        this.token = result.token;
        return result;
    }

    config() {
        return this.call<SoftphoneConfig>("GET", "/config");
    }
    history() {
        return this.call<RecentCall[]>("GET", "/history?limit=50");
    }
    directory() {
        return this.call<Directory>("GET", "/directory");
    }
    status() {
        return this.call<Status>("GET", "/status");
    }
    saveStatus(dnd: boolean, forwardEnabled: boolean, forwardTo: string) {
        return this.call<Status>("PUT", "/status", { dnd, forward_enabled: forwardEnabled, forward_to: forwardTo });
    }
    signOut() {
        return this.call<void>("DELETE", "/device");
    }
    /** The AI's handoff card for the call ringing now, if the AI sent it. */
    async handoff(number: string): Promise<HandoffCard | null> {
        const result = await this.call<{ card: HandoffCard | null }>("GET", `/handoff?number=${encodeURIComponent(number)}`);
        return result?.card ?? null;
    }
    handoffAnswered(cardId: string) {
        return this.call<void>("POST", `/handoff/${encodeURIComponent(cardId)}/answered`);
    }
}

/* ------------------------------------------------------------ storage */

const KEY = "nimbora-softphone";
export type Saved = { server: string; token: string; deviceName: string };

export function loadSaved(storage: Storage | undefined = globalThis.localStorage): Saved | null {
    try {
        const raw = storage?.getItem(KEY);
        if (!raw) return null;
        const value = JSON.parse(raw) as Saved;
        return value.server && value.token ? value : null;
    } catch {
        return null;
    }
}

export function save(value: Saved, storage: Storage | undefined = globalThis.localStorage) {
    try {
        storage?.setItem(KEY, JSON.stringify(value));
    } catch {
        // Private mode: pairing lasts for this session only.
    }
}

export function forget(storage: Storage | undefined = globalThis.localStorage) {
    try {
        storage?.removeItem(KEY);
    } catch {
        // Nothing to forget.
    }
}

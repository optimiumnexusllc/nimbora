/**
 * The SIP phone: JsSIP over the PBX's secure WebSocket, WebRTC audio.
 *
 * `Phone` owns the user agent and at most one call; the UI subscribes to its
 * snapshots. Call state transitions live in the pure `reduceCall` so they can
 * be tested without a network.
 */
import type { SoftphoneConfig } from "./api";
import { cleanNumber, numberFromUri } from "./format";

export type Registration = "disconnected" | "connecting" | "registered" | "failed";
export type CallStatus = "ringing" | "calling" | "early" | "active" | "ended";
export type Call = {
    id: string;
    direction: "incoming" | "outgoing";
    number: string;
    name: string | null;
    status: CallStatus;
    startedAt: number | null; // when answered
    muted: boolean;
    held: boolean;
    endReason: string | null;
};
export type Snapshot = { registration: Registration; error: string | null; call: Call | null };

export type CallEvent =
    | { type: "incoming"; id: string; number: string; name: string | null }
    | { type: "dialing"; id: string; number: string }
    | { type: "progress" }
    | { type: "accepted"; at: number }
    | { type: "muted"; value: boolean }
    | { type: "held"; value: boolean }
    | { type: "ended"; reason: string | null };

const END_REASONS: Record<string, string> = {
    Busy: "Occupé",
    Rejected: "Refusé",
    "Request Timeout": "Pas de réponse",
    "No Answer": "Pas de réponse",
    Unavailable: "Injoignable",
    "Not Found": "Numéro inconnu",
    "Address Incomplete": "Numéro incomplet",
    Canceled: "Annulé",
    "Connection Error": "Connexion perdue",
    "User Denied Media Access": "Micro refusé",
    "WebRTC Error": "Audio indisponible",
    "SIP Failure Code": "Appel refusé par le PBX",
};

export function endReasonLabel(cause: string | null | undefined): string | null {
    if (!cause || cause === "Terminated" || cause === "Bye") return null;
    return END_REASONS[cause] ?? cause;
}

export function reduceCall(call: Call | null, event: CallEvent): Call | null {
    switch (event.type) {
        case "incoming":
            return {
                id: event.id,
                direction: "incoming",
                number: event.number,
                name: event.name,
                status: "ringing",
                startedAt: null,
                muted: false,
                held: false,
                endReason: null,
            };
        case "dialing":
            return {
                id: event.id,
                direction: "outgoing",
                number: event.number,
                name: null,
                status: "calling",
                startedAt: null,
                muted: false,
                held: false,
                endReason: null,
            };
        case "progress":
            return call && call.status === "calling" ? { ...call, status: "early" } : call;
        case "accepted":
            return call ? { ...call, status: "active", startedAt: event.at } : call;
        case "muted":
            return call ? { ...call, muted: event.value } : call;
        case "held":
            return call ? { ...call, held: event.value } : call;
        case "ended":
            return call ? { ...call, status: "ended", endReason: endReasonLabel(event.reason) } : call;
        default:
            return call;
    }
}

/* ------------------------------------------------------------ JsSIP glue */

type JsSIPModule = typeof import("jssip");
type UA = InstanceType<JsSIPModule["UA"]>;
type RTCSession = import("jssip/lib/RTCSession").RTCSession;

type Listener = (snapshot: Snapshot) => void;

/** Registration refused for bad credentials (the SIP secret was rotated, say). */
export const AUTH_REFUSED = "Identifiants SIP refusés par le PBX";

export class Phone {
    private ua: UA | null = null;
    private session: RTCSession | null = null;
    private listeners = new Set<Listener>();
    private snapshot: Snapshot = { registration: "disconnected", error: null, call: null };
    private clearTimer: ReturnType<typeof setTimeout> | null = null;
    onIncoming: ((call: Call) => void) | null = null;

    constructor(
        private config: SoftphoneConfig,
        private audio: HTMLAudioElement | null,
        private loadJsSIP: () => Promise<JsSIPModule> = () => import("jssip"),
    ) {}

    get state(): Snapshot {
        return this.snapshot;
    }

    subscribe(listener: Listener): () => void {
        this.listeners.add(listener);
        listener(this.snapshot);
        return () => this.listeners.delete(listener);
    }

    private emit(patch: Partial<Snapshot>) {
        this.snapshot = { ...this.snapshot, ...patch };
        for (const listener of this.listeners) listener(this.snapshot);
    }

    private callEvent(event: CallEvent) {
        this.emit({ call: reduceCall(this.snapshot.call, event) });
        if (event.type === "ended") {
            this.session = null;
            if (this.clearTimer) clearTimeout(this.clearTimer);
            // Keep "Appel terminé" on screen for a moment.
            this.clearTimer = setTimeout(() => this.emit({ call: null }), 2500);
        }
    }

    async start() {
        const JsSIP = await this.loadJsSIP();
        const { account } = this.config;
        this.emit({ registration: "connecting", error: null });
        const socket = new JsSIP.WebSocketInterface(account.wss_url);
        const ua = new JsSIP.UA({
            sockets: [socket],
            uri: `sip:${account.sip_identity || account.username}@${account.sip_domain}`,
            authorization_user: account.username,
            password: account.password,
            display_name: account.display_name,
            register: true,
            session_timers: false,
            user_agent: `${this.config.brand.name} Softphone`,
            connection_recovery_min_interval: 2,
            connection_recovery_max_interval: 30,
        });
        ua.on("registered", () => this.emit({ registration: "registered", error: null }));
        ua.on("unregistered", () => this.emit({ registration: "disconnected" }));
        ua.on("disconnected", () => this.emit({ registration: "connecting", error: "Connexion au PBX perdue, nouvelle tentative…" }));
        ua.on("registrationFailed", (e: { cause?: string }) =>
            this.emit({
                registration: "failed",
                error: e.cause === "Authentication Error" ? AUTH_REFUSED : `Enregistrement impossible (${e.cause ?? "erreur"})`,
            }),
        );
        ua.on("newRTCSession", (data: { session: RTCSession; originator: string }) => {
            const session = data.session;
            if (data.originator !== "remote") return;
            if (this.session) {
                // Already on a call: busy for the second caller.
                session.terminate({ status_code: 486, reason_phrase: "Busy Here" });
                return;
            }
            this.session = session;
            this.bind(session);
            const id = String(session.id);
            const number = numberFromUri(session.remote_identity?.uri?.toString());
            const name = session.remote_identity?.display_name || null;
            this.callEvent({ type: "incoming", id, number, name });
            if (this.snapshot.call && this.onIncoming) this.onIncoming(this.snapshot.call);
        });
        this.ua = ua;
        ua.start();
    }

    stop() {
        if (this.clearTimer) clearTimeout(this.clearTimer);
        try {
            this.session?.terminate();
        } catch {
            // Already ended.
        }
        this.ua?.stop();
        this.ua = null;
        this.emit({ registration: "disconnected", call: null });
    }

    private mediaOptions() {
        return {
            mediaConstraints: { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false },
            pcConfig: { iceServers: this.config.ice_servers as RTCIceServer[] },
            rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: false },
        };
    }

    private bind(session: RTCSession) {
        session.on("peerconnection", (e: { peerconnection: RTCPeerConnection }) => this.attach(e.peerconnection));
        if (session.connection) this.attach(session.connection);
        session.on("progress", () => this.callEvent({ type: "progress" }));
        session.on("accepted", () => this.callEvent({ type: "accepted", at: Date.now() }));
        session.on("confirmed", () => {
            if (this.snapshot.call?.status !== "active") this.callEvent({ type: "accepted", at: Date.now() });
        });
        session.on("ended", (e: { cause?: string }) => this.callEvent({ type: "ended", reason: e.cause ?? null }));
        session.on("failed", (e: { cause?: string }) => this.callEvent({ type: "ended", reason: e.cause ?? null }));
        session.on("muted", () => this.callEvent({ type: "muted", value: true }));
        session.on("unmuted", () => this.callEvent({ type: "muted", value: false }));
        session.on("hold", () => this.callEvent({ type: "held", value: true }));
        session.on("unhold", () => this.callEvent({ type: "held", value: false }));
    }

    private attach(connection: RTCPeerConnection) {
        connection.addEventListener("track", (event: RTCTrackEvent) => {
            if (this.audio && event.streams[0]) {
                this.audio.srcObject = event.streams[0];
                void this.audio.play().catch(() => undefined);
            }
        });
    }

    call(target: string) {
        if (!this.ua || this.session) return;
        const number = cleanNumber(target);
        const uri = `sip:${number}@${this.config.account.sip_domain}`;
        const session = this.ua.call(uri, this.mediaOptions()) as RTCSession;
        this.session = session;
        this.bind(session);
        this.callEvent({ type: "dialing", id: String(session.id), number });
    }

    answer() {
        if (this.session && this.snapshot.call?.status === "ringing") this.session.answer(this.mediaOptions());
    }

    hangup() {
        try {
            this.session?.terminate();
        } catch {
            this.callEvent({ type: "ended", reason: null });
        }
    }

    decline() {
        try {
            this.session?.terminate({ status_code: 603, reason_phrase: "Decline" });
        } catch {
            this.callEvent({ type: "ended", reason: null });
        }
    }

    toggleMute() {
        if (!this.session) return;
        if (this.snapshot.call?.muted) this.session.unmute({ audio: true });
        else this.session.mute({ audio: true });
    }

    toggleHold() {
        if (!this.session) return;
        if (this.snapshot.call?.held) this.session.unhold();
        else this.session.hold();
    }

    dtmf(tone: string) {
        if (this.session && this.snapshot.call?.status === "active") this.session.sendDTMF(tone, { transportType: "RFC2833" } as unknown as Parameters<RTCSession["sendDTMF"]>[1]);
    }

    /** Blind transfer: the PBX takes over and calls the target. */
    transfer(target: string) {
        if (!this.session || this.snapshot.call?.status !== "active") return;
        const number = cleanNumber(target);
        this.session.refer(`sip:${number}@${this.config.account.sip_domain}`);
    }

    setOutputDevice(deviceId: string) {
        const audio = this.audio as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> };
        if (audio?.setSinkId) void audio.setSinkId(deviceId).catch(() => undefined);
    }
}

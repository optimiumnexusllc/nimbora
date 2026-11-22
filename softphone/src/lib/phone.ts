/**
 * The SIP phone: JsSIP over the PBX's secure WebSocket, WebRTC audio.
 *
 * `Phone` owns the user agent and at most one call; the UI subscribes to its
 * snapshots. Call state transitions live in the pure `reduceCall` so they can
 * be tested without a network.
 */
import type { SoftphoneConfig } from "./api";
import { ConferenceMixer, remoteStream } from "./conference";
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
    /** Rung by an intercom or an announcement (answered by the app). */
    intercom?: boolean;
};
export type Snapshot = {
    registration: Registration;
    error: string | null;
    /** The customer's call (or the only call). */
    call: Call | null;
    /** The colleague consulted while the customer waits on hold. */
    consult: Call | null;
    /** Both calls mixed: the three people hear each other. */
    conference: boolean;
    /** A short message about the last transfer or conference attempt. */
    notice: string | null;
};
type Role = "main" | "consult";

export type CallEvent =
    | { type: "incoming"; id: string; number: string; name: string | null; intercom?: boolean }
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

/**
 * Is this INVITE from an intercom or an announcement? Paging asks phones to
 * answer by themselves with Call-Info « answer-after=0 » or an Alert-Info
 * « auto answer » / « intercom » (the header differs between phone makers).
 */
export function isIntercom(headers: { callInfo?: string | null; alertInfo?: string | null }): boolean {
    const callInfo = (headers.callInfo || "").toLowerCase();
    const alertInfo = (headers.alertInfo || "").toLowerCase();
    return /answer-after\s*=\s*0/.test(callInfo) || /auto[-_ ]?answer|intercom|ring answer/.test(alertInfo);
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
                intercom: !!event.intercom,
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
    private consultSession: RTCSession | null = null;
    /** Hanging up our own legs after the PBX accepted a transfer: no unhold, no promotion. */
    private transferring = false;
    private mixer: ConferenceMixer;
    private listeners = new Set<Listener>();
    private snapshot: Snapshot = { registration: "disconnected", error: null, call: null, consult: null, conference: false, notice: null };
    private clearTimer: ReturnType<typeof setTimeout> | null = null;
    onIncoming: ((call: Call) => void) | null = null;

    constructor(
        private config: SoftphoneConfig,
        private audio: HTMLAudioElement | null,
        private loadJsSIP: () => Promise<JsSIPModule> = () => import("jssip"),
        makeMixer: () => ConferenceMixer = () => new ConferenceMixer(),
    ) {
        this.mixer = makeMixer();
    }

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

    private callEvent(event: CallEvent, role: Role = "main") {
        if (role === "consult") {
            this.emit({ consult: reduceCall(this.snapshot.consult, event) });
            if (event.type === "ended") this.consultEnded();
            return;
        }
        this.emit({ call: reduceCall(this.snapshot.call, event) });
        if (event.type !== "ended") return;
        if (!this.transferring && this.consultSession && this.snapshot.consult && this.snapshot.consult.status !== "ended") {
            // The customer hung up while the colleague is on the line: the
            // colleague's call simply becomes the call.
            void this.endConference();
            this.session = this.consultSession;
            this.consultSession = null;
            this.emit({ call: this.snapshot.consult, consult: null, conference: false });
            this.listenTo(this.session);
            return;
        }
        this.session = null;
        if (this.clearTimer) clearTimeout(this.clearTimer);
        // Keep "Appel terminé" on screen for a moment.
        this.clearTimer = setTimeout(() => this.emit({ call: null, notice: null }), 2500);
    }

    private consultEnded() {
        this.consultSession = null;
        void this.endConference();
        this.emit({ consult: null, conference: false });
        // Back to the customer (unless we are hanging up after a transfer).
        if (!this.transferring && this.session && this.snapshot.call?.status === "active") {
            if (this.snapshot.call.held) this.session.unhold();
            this.listenTo(this.session);
        }
    }

    private async endConference() {
        if (this.mixer.active) await this.mixer.stop();
    }

    /** Play one call's voice (the other is on hold). */
    private listenTo(session: RTCSession | null) {
        const stream = remoteStream(session?.connection);
        if (this.audio && stream) {
            this.audio.srcObject = stream;
            void this.audio.play().catch(() => undefined);
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
        ua.on("newRTCSession", (data: { session: RTCSession; originator: string; request?: { getHeader?: (name: string) => string | undefined } }) => {
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
            const intercom = isIntercom({
                callInfo: data.request?.getHeader?.("Call-Info"),
                alertInfo: data.request?.getHeader?.("Alert-Info"),
            });
            this.callEvent({ type: "incoming", id, number, name, intercom });
            if (intercom && this.config.features.intercom_auto_answer !== false) {
                // An intercom does not ring: it answers, like a desk phone's speaker.
                this.answer();
                return;
            }
            if (this.snapshot.call && this.onIncoming) this.onIncoming(this.snapshot.call);
        });
        this.ua = ua;
        ua.start();
    }

    stop() {
        if (this.clearTimer) clearTimeout(this.clearTimer);
        void this.endConference();
        for (const session of [this.consultSession, this.session]) {
            try {
                session?.terminate();
            } catch {
                // Already ended.
            }
        }
        this.ua?.stop();
        this.ua = null;
        this.emit({ registration: "disconnected", call: null, consult: null, conference: false });
    }

    private mediaOptions() {
        return {
            mediaConstraints: { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false },
            pcConfig: { iceServers: this.config.ice_servers as RTCIceServer[] },
            rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: false },
        };
    }

    private bind(session: RTCSession, role: Role = "main") {
        const on = (event: CallEvent) => this.callEvent(event, role);
        session.on("peerconnection", (e: { peerconnection: RTCPeerConnection }) => this.attach(e.peerconnection));
        if (session.connection) this.attach(session.connection);
        session.on("progress", () => on({ type: "progress" }));
        session.on("accepted", () => on({ type: "accepted", at: Date.now() }));
        session.on("confirmed", () => {
            const call = role === "main" ? this.snapshot.call : this.snapshot.consult;
            if (call?.status !== "active") on({ type: "accepted", at: Date.now() });
        });
        session.on("ended", (e: { cause?: string }) => on({ type: "ended", reason: e.cause ?? null }));
        session.on("failed", (e: { cause?: string }) => on({ type: "ended", reason: e.cause ?? null }));
        session.on("muted", () => on({ type: "muted", value: true }));
        session.on("unmuted", () => on({ type: "muted", value: false }));
        session.on("hold", () => on({ type: "held", value: true }));
        session.on("unhold", () => on({ type: "held", value: false }));
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

    /** Hang up the customer's call (and the consultation, if any). */
    hangup() {
        try {
            this.consultSession?.terminate();
        } catch {
            this.callEvent({ type: "ended", reason: null }, "consult");
        }
        try {
            this.session?.terminate();
        } catch {
            this.callEvent({ type: "ended", reason: null });
        }
    }

    /** The call being talked to now: the colleague during a consultation. */
    private current(): { session: RTCSession | null; call: Call | null } {
        if (this.consultSession && this.snapshot.consult && !this.snapshot.consult.held && !this.snapshot.conference) {
            return { session: this.consultSession, call: this.snapshot.consult };
        }
        return { session: this.session, call: this.snapshot.call };
    }

    decline() {
        try {
            this.session?.terminate({ status_code: 603, reason_phrase: "Decline" });
        } catch {
            this.callEvent({ type: "ended", reason: null });
        }
    }

    toggleMute() {
        if (this.snapshot.conference && this.mixer.mic) {
            // One microphone feeds both calls.
            const muted = !this.snapshot.call?.muted;
            this.mixer.mic.enabled = !muted;
            this.callEvent({ type: "muted", value: muted });
            this.callEvent({ type: "muted", value: muted }, "consult");
            return;
        }
        const { session, call } = this.current();
        if (!session) return;
        if (call?.muted) session.unmute({ audio: true });
        else session.mute({ audio: true });
    }

    toggleHold() {
        if (!this.session || this.consultSession) return; // « Basculer » during a consultation
        if (this.snapshot.call?.held) this.session.unhold();
        else this.session.hold();
    }

    dtmf(tone: string) {
        const { session, call } = this.current();
        if (session && call?.status === "active") session.sendDTMF(tone, { transportType: "RFC2833" } as unknown as Parameters<RTCSession["sendDTMF"]>[1]);
    }

    /** Blind transfer: the PBX takes over and calls the target. */
    transfer(target: string) {
        if (!this.session || this.snapshot.call?.status !== "active" || this.consultSession) return;
        const number = cleanNumber(target);
        this.session.refer(`sip:${number}@${this.config.account.sip_domain}`);
    }

    /** Put the customer on hold and call a colleague (consultation). */
    consult(target: string) {
        if (!this.ua || !this.session || this.consultSession || this.snapshot.call?.status !== "active") return;
        const number = cleanNumber(target);
        if (!this.snapshot.call.held) this.session.hold();
        const session = this.ua.call(`sip:${number}@${this.config.account.sip_domain}`, this.mediaOptions()) as RTCSession;
        this.consultSession = session;
        this.bind(session, "consult");
        this.emit({ notice: null });
        this.callEvent({ type: "dialing", id: String(session.id), number }, "consult");
    }

    /** Talk to the other one: the customer or the colleague. */
    swap() {
        if (!this.session || !this.consultSession || this.snapshot.conference) return;
        if (this.snapshot.consult?.status !== "active") return;
        if (this.snapshot.call?.held) {
            this.consultSession.hold();
            this.session.unhold();
            this.listenTo(this.session);
        } else {
            this.session.hold();
            this.consultSession.unhold();
            this.listenTo(this.consultSession);
        }
    }

    /** Hang up on the colleague and go back to the customer. */
    cancelConsult() {
        try {
            this.consultSession?.terminate();
        } catch {
            this.callEvent({ type: "ended", reason: null }, "consult");
        }
    }

    /**
     * Connect the customer and the colleague, and leave. Once the colleague
     * has answered: attended transfer (REFER with Replaces, the PBX bridges
     * the two calls). While it still rings: the PBX calls the colleague for
     * the customer (blind transfer).
     */
    completeTransfer() {
        const main = this.session;
        const consult = this.consultSession;
        if (!main || !consult || this.snapshot.call?.status !== "active") return;
        const target = this.snapshot.consult;
        const options = {
            eventHandlers: {
                failed: () => this.emit({ notice: "Transfert refusé par le PBX" }),
                accepted: () => {
                    // The PBX has connected the two others (NOTIFY 200 OK): the
                    // employee's own legs are over. Hang them up here rather than
                    // wait for the PBX's BYE, which came 8 s later on the lab and
                    // left a phantom "active" call that refused new callers.
                    this.emit({ notice: "Appel transféré" });
                    this.transferring = true;
                    try {
                        for (const session of [consult, main]) {
                            if (typeof session.isEnded === "function" && session.isEnded()) continue;
                            try {
                                session.terminate();
                            } catch {
                                /* already gone */
                            }
                        }
                    } finally {
                        this.transferring = false;
                    }
                },
            },
        };
        void this.endConference();
        if (target?.status === "active") {
            main.refer(consult.remote_identity.uri, { ...options, replaces: consult } as never);
        } else if (target) {
            this.cancelConsult();
            main.refer(`sip:${target.number}@${this.config.account.sip_domain}`, options as never);
        }
    }

    /** Everybody together: the customer, the colleague and the employee. */
    async startConference(): Promise<boolean> {
        if (!this.session || !this.consultSession || this.snapshot.conference) return false;
        if (this.snapshot.call?.status !== "active" || this.snapshot.consult?.status !== "active") return false;
        if (this.snapshot.call.held) this.session.unhold();
        if (this.snapshot.consult.held) this.consultSession.unhold();
        const mixed = await this.mixer.start([{ connection: this.session.connection }, { connection: this.consultSession.connection }], this.audio);
        if (!mixed) {
            this.emit({ notice: "Conférence impossible : audio indisponible" });
            return false;
        }
        this.emit({ conference: true, notice: null });
        return true;
    }

    setOutputDevice(deviceId: string) {
        const audio = this.audio as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> };
        if (audio?.setSinkId) void audio.setSinkId(deviceId).catch(() => undefined);
    }
}

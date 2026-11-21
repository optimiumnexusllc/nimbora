import { describe, expect, it, vi } from "vitest";

import type { SoftphoneConfig } from "./api";
import { endReasonLabel, Phone, reduceCall } from "./phone";

const config: SoftphoneConfig = {
    brand: { name: "NIMBORA", pbx_name: "NIMBORA Voice" },
    device: { id: 1, name: "PC", platform: "windows" },
    account: {
        display_name: "Koffi Yao",
        extension: "1001",
        username: "koffi1001",
        password: "secret",
        wss_url: "wss://pbx.example/api/asterisk/ws",
        sip_domain: "pbx.example",
    },
    ice_servers: [{ urls: ["stun:stun.example:3478"] }],
    features: { voicemail_code: "*98", transfer: true, dnd: true },
};

describe("reduceCall", () => {
    it("follows an outgoing call from dialling to the end", () => {
        let call = reduceCall(null, { type: "dialing", id: "1", number: "1002" });
        expect(call?.status).toBe("calling");
        call = reduceCall(call, { type: "progress" });
        expect(call?.status).toBe("early");
        call = reduceCall(call, { type: "accepted", at: 1000 });
        expect(call).toMatchObject({ status: "active", startedAt: 1000 });
        call = reduceCall(call, { type: "muted", value: true });
        call = reduceCall(call, { type: "held", value: true });
        expect(call).toMatchObject({ muted: true, held: true });
        call = reduceCall(call, { type: "ended", reason: "Busy" });
        expect(call).toMatchObject({ status: "ended", endReason: "Occupé" });
    });

    it("labels why a call ended", () => {
        expect(endReasonLabel("Terminated")).toBeNull();
        expect(endReasonLabel("User Denied Media Access")).toBe("Micro refusé");
        expect(endReasonLabel("Something else")).toBe("Something else");
        expect(reduceCall(null, { type: "progress" })).toBeNull();
    });
});

/* A tiny JsSIP stand-in: enough to drive the Phone like the real UA. */
type Handler = (data: unknown) => void;
class Emitter {
    handlers: Record<string, Handler[]> = {};
    on(event: string, handler: Handler) {
        (this.handlers[event] ??= []).push(handler);
    }
    fire(event: string, data: unknown = {}) {
        for (const handler of this.handlers[event] ?? []) handler(data);
    }
}
class FakeSession extends Emitter {
    id = "s-1";
    connection = null;
    remote_identity = { uri: { toString: () => "sip:+2250707112233@pbx.example" }, display_name: "Awa" };
    answer = vi.fn(() => this.fire("accepted"));
    terminate = vi.fn((options?: { status_code?: number }) => this.fire("ended", { cause: options?.status_code === 486 ? "Busy" : "Terminated" }));
    mute = vi.fn(() => this.fire("muted"));
    unmute = vi.fn(() => this.fire("unmuted"));
    hold = vi.fn(() => this.fire("hold"));
    unhold = vi.fn(() => this.fire("unhold"));
    sendDTMF = vi.fn();
    refer = vi.fn();
}
let ua: FakeUA;
class FakeUA extends Emitter {
    options: Record<string, unknown>;
    started = false;
    lastCall: FakeSession | null = null;
    constructor(options: Record<string, unknown>) {
        super();
        this.options = options;
        ua = this;
    }
    start() {
        this.started = true;
    }
    stop() {
        this.started = false;
    }
    call(uri: string, options: unknown) {
        this.lastCall = Object.assign(new FakeSession(), { uri, options });
        return this.lastCall;
    }
}
const fakeJsSIP = { UA: FakeUA, WebSocketInterface: class { constructor(public url: string) {} } } as never;

describe("Phone", () => {
    it("registers on the PBX with the account from the platform", async () => {
        const phone = new Phone(config, null, async () => fakeJsSIP);
        const states: string[] = [];
        phone.subscribe((s) => states.push(s.registration));
        await phone.start();
        expect(ua.options).toMatchObject({ uri: "sip:koffi1001@pbx.example", password: "secret", display_name: "Koffi Yao", register: true });
        expect((ua.options.sockets as { url: string }[])[0].url).toBe("wss://pbx.example/api/asterisk/ws");
        ua.fire("registered");
        expect(phone.state.registration).toBe("registered");
        ua.fire("registrationFailed", { cause: "Authentication Error" });
        expect(phone.state.error).toBe("Identifiants SIP refusés par le PBX");
        expect(states).toContain("connecting");
    });

    it("answers, mutes, holds, sends DTMF, transfers and rejects a second caller", async () => {
        vi.useFakeTimers();
        const phone = new Phone(config, null, async () => fakeJsSIP);
        const ringing = vi.fn();
        phone.onIncoming = ringing;
        await phone.start();
        const session = new FakeSession();
        ua.fire("newRTCSession", { session, originator: "remote" });
        expect(phone.state.call).toMatchObject({ direction: "incoming", number: "+2250707112233", name: "Awa", status: "ringing" });
        expect(ringing).toHaveBeenCalled();

        const second = new FakeSession();
        ua.fire("newRTCSession", { session: second, originator: "remote" });
        expect(second.terminate).toHaveBeenCalledWith({ status_code: 486, reason_phrase: "Busy Here" });

        phone.answer();
        expect(phone.state.call?.status).toBe("active");
        phone.toggleMute();
        expect(phone.state.call?.muted).toBe(true);
        phone.toggleMute();
        expect(session.unmute).toHaveBeenCalled();
        phone.toggleHold();
        expect(phone.state.call?.held).toBe(true);
        phone.dtmf("5");
        expect(session.sendDTMF).toHaveBeenCalledWith("5", { transportType: "RFC2833" });
        phone.transfer("10 02");
        expect(session.refer).toHaveBeenCalledWith("sip:1002@pbx.example");
        phone.hangup();
        expect(phone.state.call?.status).toBe("ended");
        vi.advanceTimersByTime(3000);
        expect(phone.state.call).toBeNull();
        vi.useRealTimers();
    });

    it("places calls to the PBX's domain with the ICE servers", async () => {
        const phone = new Phone(config, null, async () => fakeJsSIP);
        await phone.start();
        phone.call("+225 07 07 11 22 33");
        const placed = ua.lastCall as unknown as { uri: string; options: { pcConfig: { iceServers: unknown } } };
        expect(placed.uri).toBe("sip:+2250707112233@pbx.example");
        expect(placed.options.pcConfig.iceServers).toEqual(config.ice_servers);
        expect(phone.state.call).toMatchObject({ direction: "outgoing", status: "calling" });
    });
});

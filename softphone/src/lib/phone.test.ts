import { describe, expect, it, vi } from "vitest";

import type { SoftphoneConfig } from "./api";
import { endReasonLabel, Phone, reduceCall } from "./phone";

const config: SoftphoneConfig = {
    brand: { name: "NIMBORA", pbx_name: "NIMBORA Voice" },
    device: { id: 1, name: "PC", platform: "windows" },
    account: {
        display_name: "Koffi Yao",
        extension: "1001",
        sip_identity: "k0ff1y40",
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
let sessionCount = 0;
class FakeSession extends Emitter {
    id = `s-${++sessionCount}`;
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
        expect(ua.options).toMatchObject({ uri: "sip:k0ff1y40@pbx.example", authorization_user: "koffi1001", password: "secret", display_name: "Koffi Yao", register: true });
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

describe("Phone · consultation, attended transfer, conference", () => {
    function fakeMixer() {
        const mixer = {
            active: false,
            mic: { enabled: true } as MediaStreamTrack,
            start: vi.fn(async () => {
                mixer.active = true;
                return true;
            }),
            stop: vi.fn(async () => {
                mixer.active = false;
            }),
        };
        return mixer;
    }

    async function onACall() {
        const mixer = fakeMixer();
        const phone = new Phone(config, null, async () => fakeJsSIP, () => mixer as never);
        await phone.start();
        const customer = new FakeSession();
        ua.fire("newRTCSession", { session: customer, originator: "remote" });
        phone.answer();
        return { phone, customer, mixer };
    }

    it("puts the customer on hold, calls a colleague, swaps, then transfers attended", async () => {
        const { phone, customer } = await onACall();
        phone.consult("1002");
        expect(customer.hold).toHaveBeenCalled();
        const colleague = ua.lastCall!;
        expect((colleague as unknown as { uri: string }).uri).toBe("sip:1002@pbx.example");
        expect(phone.state.consult).toMatchObject({ number: "1002", status: "calling" });
        expect(phone.state.call?.held).toBe(true);

        // Hold and blind transfer are off during a consultation.
        phone.toggleHold();
        phone.transfer("1003");
        expect(customer.refer).not.toHaveBeenCalled();

        colleague.fire("accepted");
        expect(phone.state.consult?.status).toBe("active");
        phone.swap();
        expect(colleague.hold).toHaveBeenCalled();
        expect(customer.unhold).toHaveBeenCalled();
        phone.swap();
        expect(colleague.unhold).toHaveBeenCalled();

        // DTMF and mute go to the colleague, the person being talked to.
        phone.dtmf("1");
        expect(colleague.sendDTMF).toHaveBeenCalled();
        expect(customer.sendDTMF).not.toHaveBeenCalled();

        phone.completeTransfer();
        const [target, options] = customer.refer.mock.calls[0] as unknown as [unknown, { replaces: unknown; eventHandlers: { failed: () => void } }];
        expect(target).toBe(colleague.remote_identity.uri);
        expect(options.replaces).toBe(colleague);
        options.eventHandlers.failed();
        expect(phone.state.notice).toBe("Transfert refusé par le PBX");
    });

    it("hangs up its own two legs once the PBX has accepted the transfer", async () => {
        const { phone, customer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        colleague.fire("accepted");
        phone.completeTransfer();
        const options = customer.refer.mock.calls[0][1] as unknown as { eventHandlers: { accepted: () => void } };
        options.eventHandlers.accepted();
        expect(phone.state.notice).toBe("Appel transféré");
        expect(colleague.terminate).toHaveBeenCalled();
        expect(customer.terminate).toHaveBeenCalled();
        expect(phone.state.call?.status ?? "ended").toBe("ended");
    });

    it("transfers to a colleague whose phone still rings (blind, through the PBX)", async () => {
        const { phone, customer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        phone.completeTransfer();
        expect(colleague.terminate).toHaveBeenCalled();
        expect(customer.refer.mock.calls[0][0]).toBe("sip:1002@pbx.example");
    });

    it("cancels the consultation and goes back to the customer", async () => {
        const { phone, customer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        colleague.fire("accepted");
        phone.cancelConsult();
        expect(phone.state.consult).toBeNull();
        expect(customer.unhold).toHaveBeenCalled();
        expect(phone.state.call?.status).toBe("active");
    });

    it("keeps the colleague on the line when the customer hangs up", async () => {
        const { phone, customer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        colleague.fire("accepted");
        customer.fire("ended", { cause: "Terminated" });
        expect(phone.state.consult).toBeNull();
        expect(phone.state.call).toMatchObject({ number: "1002", status: "active" });
        phone.hangup();
        expect(colleague.terminate).toHaveBeenCalled();
    });

    it("mixes a three-way conference, mutes both, then leaves them together", async () => {
        const { phone, customer, mixer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        expect(await phone.startConference()).toBe(false); // not answered yet
        colleague.fire("accepted");
        expect(await phone.startConference()).toBe(true);
        expect(customer.unhold).toHaveBeenCalled();
        expect(mixer.start).toHaveBeenCalled();
        expect(phone.state.conference).toBe(true);

        phone.toggleMute();
        expect(mixer.mic.enabled).toBe(false);
        expect(phone.state.call?.muted && phone.state.consult?.muted).toBe(true);
        phone.swap(); // no swapping in a conference
        expect(colleague.hold).not.toHaveBeenCalled();

        // « Se retirer »: the PBX bridges the two others.
        phone.completeTransfer();
        expect(mixer.stop).toHaveBeenCalled();
        expect((customer.refer.mock.calls[0][1] as { replaces: unknown }).replaces).toBe(colleague);
    });

    it("ends the conference when the colleague leaves", async () => {
        const { phone, mixer } = await onACall();
        phone.consult("1002");
        const colleague = ua.lastCall!;
        colleague.fire("accepted");
        await phone.startConference();
        colleague.fire("ended", { cause: "Terminated" });
        expect(mixer.stop).toHaveBeenCalled();
        expect(phone.state).toMatchObject({ conference: false, consult: null });
        expect(phone.state.call?.status).toBe("active");
    });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConferenceMixer } from "./conference";

class FakeStream {
    constructor(public tracks: unknown[] = []) {}
    getAudioTracks() {
        return this.tracks;
    }
}
const track = (id: string) => ({ id, kind: "audio", enabled: true });

function connection(name: string) {
    const sender = { track: track(`${name}-mic`), replaceTrack: vi.fn(async function (this: { track: unknown }, t: unknown) { this.track = t; }) };
    return {
        sender,
        getSenders: () => [sender],
        getReceivers: () => [{ track: track(`${name}-voice`) }],
    };
}

function fakeContext() {
    const nodes: { from: string; to: string[] }[] = [];
    let outputs = 0;
    const ctx = {
        nodes,
        closed: false,
        createMediaStreamSource: (stream: FakeStream) => {
            const node = { from: (stream.tracks[0] as { id: string }).id, to: [] as string[], connect: (dest: { name: string }) => node.to.push(dest.name) };
            nodes.push(node);
            return node;
        },
        createMediaStreamDestination: () => {
            const name = `out-${++outputs}`;
            return { name, stream: new FakeStream([{ id: name, kind: "audio" }]) };
        },
        close: vi.fn(async () => {
            ctx.closed = true;
        }),
    };
    return ctx;
}

beforeEach(() => vi.stubGlobal("MediaStream", FakeStream));
afterEach(() => vi.unstubAllGlobals());

describe("ConferenceMixer", () => {
    it("sends each call the microphone and the other call, plays both, then restores", async () => {
        const ctx = fakeContext();
        const mixer = new ConferenceMixer(() => ctx as never);
        const customer = connection("customer");
        const colleague = connection("colleague");
        const audio = { srcObject: null as unknown, play: vi.fn(async () => undefined) };

        const started = await mixer.start([{ connection: customer as never }, { connection: colleague as never }], audio as never);
        expect(started).toBe(true);
        expect(mixer.active).toBe(true);
        expect(mixer.mic).toMatchObject({ id: "customer-mic" });

        const routes = Object.fromEntries(ctx.nodes.map((n) => [n.from, n.to]));
        // out-1 goes to the customer, out-2 to the colleague, out-3 to the speaker.
        expect(routes["customer-mic"]).toEqual(["out-1", "out-2"]);
        expect(routes["colleague-voice"]).toEqual(["out-1", "out-3"]);
        expect(routes["customer-voice"]).toEqual(["out-2", "out-3"]);
        expect(customer.sender.track).toMatchObject({ id: "out-1" });
        expect(colleague.sender.track).toMatchObject({ id: "out-2" });
        expect(audio.srcObject).toBeInstanceOf(FakeStream);

        await mixer.stop();
        expect(customer.sender.track).toMatchObject({ id: "customer-mic" });
        expect(colleague.sender.track).toMatchObject({ id: "colleague-mic" });
        expect(ctx.closed).toBe(true);
        expect(mixer.active).toBe(false);
    });

    it("refuses a call without audio yet and changes nothing", async () => {
        const ctx = fakeContext();
        const mixer = new ConferenceMixer(() => ctx as never);
        const silent = { getSenders: () => [], getReceivers: () => [] };
        expect(await mixer.start([{ connection: connection("a") as never }, { connection: silent as never }], null)).toBe(false);
        expect(mixer.active).toBe(false);
        expect(ctx.nodes).toHaveLength(0);
    });
});

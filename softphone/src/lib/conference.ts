/**
 * Three-way conference mixed in the app (WebAudio).
 *
 * The employee is on two calls (the customer and the colleague they
 * consulted). Each call receives the employee's microphone plus the other
 * call's voice; the employee hears both. Nothing is needed on the PBX, and
 * « Se retirer » hands the two others to each other with an attended
 * transfer, so the PBX keeps them connected without the app.
 */

export type Leg = { connection: RTCPeerConnection | null | undefined };

type AudioContextLike = Pick<AudioContext, "createMediaStreamSource" | "createMediaStreamDestination" | "close">;

function audioSender(connection: RTCPeerConnection): RTCRtpSender | undefined {
    return connection.getSenders().find((s) => s.track?.kind === "audio");
}

export function remoteStream(connection: RTCPeerConnection | null | undefined): MediaStream | null {
    if (!connection) return null;
    const tracks = connection
        .getReceivers()
        .map((r) => r.track)
        .filter((t): t is MediaStreamTrack => !!t && t.kind === "audio");
    return tracks.length ? new MediaStream(tracks) : null;
}

export class ConferenceMixer {
    private ctx: AudioContextLike | null = null;
    private restore: { sender: RTCRtpSender; track: MediaStreamTrack | null }[] = [];
    /** The microphone track every mix starts from (muting it mutes both calls). */
    mic: MediaStreamTrack | null = null;

    constructor(private makeContext: () => AudioContextLike = () => new AudioContext()) {}

    get active(): boolean {
        return this.ctx !== null;
    }

    /** Mix two calls; returns false (and changes nothing) if a call has no audio yet. */
    async start(legs: [Leg, Leg], audio: HTMLAudioElement | null): Promise<boolean> {
        const [a, b] = legs.map((l) => l.connection);
        if (!a || !b) return false;
        const senders = [audioSender(a), audioSender(b)];
        const remotes = [remoteStream(a), remoteStream(b)];
        const mic = senders[0]?.track ?? null;
        if (!senders[0] || !senders[1] || !remotes[0] || !remotes[1] || !mic) return false;

        const ctx = this.makeContext();
        const micNode = ctx.createMediaStreamSource(new MediaStream([mic]));
        const remoteNodes = remotes.map((stream) => ctx.createMediaStreamSource(stream as MediaStream));
        this.restore = senders.map((sender) => ({ sender: sender as RTCRtpSender, track: (sender as RTCRtpSender).track }));
        for (const i of [0, 1]) {
            const out = ctx.createMediaStreamDestination();
            micNode.connect(out);
            remoteNodes[1 - i].connect(out);
            await (senders[i] as RTCRtpSender).replaceTrack(out.stream.getAudioTracks()[0]);
        }
        const local = ctx.createMediaStreamDestination();
        remoteNodes[0].connect(local);
        remoteNodes[1].connect(local);
        if (audio) {
            audio.srcObject = local.stream;
            void audio.play().catch(() => undefined);
        }
        this.ctx = ctx;
        this.mic = mic;
        return true;
    }

    /** Back to one call: each call gets its own microphone track again. */
    async stop(): Promise<void> {
        for (const { sender, track } of this.restore) {
            try {
                await sender.replaceTrack(track);
            } catch {
                // The call has ended: nothing to restore.
            }
        }
        this.restore = [];
        this.mic = null;
        const ctx = this.ctx;
        this.ctx = null;
        try {
            await ctx?.close();
        } catch {
            // Already closed.
        }
    }
}

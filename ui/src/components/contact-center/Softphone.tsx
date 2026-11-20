"use client";

/**
 * Browser softphone for contact-center agents (SIP over secure WebSocket to the
 * platform Asterisk, via JsSIP). The SIP password is never stored by the
 * platform: the agent types it once; it is kept for this browser tab only.
 */
import { Headphones, Mic, MicOff, Pause, Phone, PhoneOff, Play } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { HandoffCard } from "@/components/contact-center/HandoffCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type Agent, enterpriseApi, type Handoff } from "@/lib/enterpriseApi";

type JsSIPModule = typeof import("jssip");
type UA = InstanceType<JsSIPModule["UA"]>;
type RTCSession = import("jssip/lib/RTCSession").RTCSession;

type Status = "disconnected" | "connecting" | "registered" | "error";

const SESSION_KEY = "nimbora-softphone-password";
const HANDOFF_HEADER = "X-Nimbora-Handoff";
const CALLBACK_HEADER = "X-Nimbora-Callback";

function inviteHeader(session: RTCSession, name: string): string | null {
    try {
        // JsSIP exposes the INVITE as `request` on incoming sessions.
        const invite = (session as unknown as { request?: { getHeader?: (h: string) => string | undefined } })
            .request;
        return invite?.getHeader?.(name) || null;
    } catch {
        return null;
    }
}
// The AI summary is generated after the card: refresh while it is pending.
const HANDOFF_POLL_MS = 1500;
const HANDOFF_POLL_MAX = 20;

function wssUrlFromLocation(): string {
    if (typeof window === "undefined") return "";
    return `wss://${window.location.host}/sip`;
}

export function Softphone({ seat, realm = "nimbora" }: { seat: Agent; realm?: string }) {
    const [password, setPassword] = useState("");
    const [status, setStatus] = useState<Status>("disconnected");
    const [incoming, setIncoming] = useState<RTCSession | null>(null);
    const [active, setActive] = useState<RTCSession | null>(null);
    const [muted, setMuted] = useState(false);
    const [paused, setPaused] = useState(false);
    const [peer, setPeer] = useState<string>("");
    const [handoff, setHandoff] = useState<Handoff | null>(null);
    // Set when this ringing call is a click-to-call callback (our own originate).
    const [callbackCall, setCallbackCall] = useState<string | null>(null);
    const handoffPoll = useRef<ReturnType<typeof setTimeout> | null>(null);
    const uaRef = useRef<UA | null>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    useEffect(() => {
        try {
            const saved = sessionStorage.getItem(SESSION_KEY);
            if (saved) setPassword(saved);
        } catch {
            // Storage can be unavailable (privacy mode); typing it again works.
        }
        return () => {
            uaRef.current?.stop();
        };
    }, []);

    const attachRemoteAudio = useCallback((session: RTCSession) => {
        session.connection?.addEventListener("track", (event: RTCTrackEvent) => {
            if (audioRef.current && event.streams[0]) {
                audioRef.current.srcObject = event.streams[0];
                void audioRef.current.play().catch(() => undefined);
            }
        });
    }, []);

    const stopHandoffPoll = () => {
        if (handoffPoll.current) clearTimeout(handoffPoll.current);
        handoffPoll.current = null;
    };

    // Load the AI handoff card for a ringing call: by the id Asterisk put in
    // the SIP header, otherwise the newest pending card of my queues.
    const loadHandoff = useCallback(async (session: RTCSession) => {
        stopHandoffPoll();
        const id = inviteHeader(session, HANDOFF_HEADER);
        try {
            let card: Handoff | null = null;
            if (id) card = await enterpriseApi.getHandoff(id);
            else card = (await enterpriseApi.myPendingHandoffs())[0] ?? null;
            if (!card) return;
            setHandoff(card);
            let attempts = 0;
            const refresh = async () => {
                attempts += 1;
                try {
                    const latest = await enterpriseApi.getHandoff(card!.id);
                    setHandoff(latest);
                    if (latest.summary_status === "pending" && attempts < HANDOFF_POLL_MAX) {
                        handoffPoll.current = setTimeout(refresh, HANDOFF_POLL_MS);
                    }
                } catch {
                    // Keep the card we have.
                }
            };
            if (card.summary_status === "pending") {
                handoffPoll.current = setTimeout(refresh, HANDOFF_POLL_MS);
            }
        } catch {
            // No card (direct call between colleagues, or not an AI transfer).
        }
    }, []);

    useEffect(() => stopHandoffPoll, []);

    const connect = async () => {
        if (!password) {
            toast.error("Saisissez le mot de passe SIP de votre poste.");
            return;
        }
        setStatus("connecting");
        const JsSIP = await import("jssip");
        const socket = new JsSIP.WebSocketInterface(wssUrlFromLocation());
        const ua = new JsSIP.UA({
            sockets: [socket],
            uri: `sip:${seat.sip_username}@${realm}`,
            authorization_user: seat.sip_username,
            password,
            realm,
            display_name: seat.display_name,
            register: true,
            session_timers: false,
        });
        ua.on("registered", () => {
            setStatus("registered");
            try {
                sessionStorage.setItem(SESSION_KEY, password);
            } catch {
                // ignore
            }
        });
        ua.on("registrationFailed", () => {
            setStatus("error");
            toast.error("Connexion refusée : vérifiez le mot de passe du poste.");
        });
        ua.on("disconnected", () => setStatus((s) => (s === "error" ? s : "disconnected")));
        ua.on("newRTCSession", (data: { session: RTCSession; originator: string }) => {
            const session = data.session;
            if (data.originator !== "remote") return;
            setPeer(session.remote_identity?.display_name || session.remote_identity?.uri?.user || "Appelant");
            setIncoming(session);
            const callbackId = inviteHeader(session, CALLBACK_HEADER);
            setCallbackCall(callbackId);
            // A callback is not an AI transfer: never show a queue's handoff card.
            if (!callbackId) void loadHandoff(session);
            session.on("ended", () => {
                setActive(null);
                setIncoming(null);
                setMuted(false);
                stopHandoffPoll();
                setHandoff(null);
                setCallbackCall(null);
            });
            session.on("failed", () => {
                setActive(null);
                setIncoming(null);
                stopHandoffPoll();
                setHandoff(null);
                setCallbackCall(null);
            });
        });
        ua.start();
        uaRef.current = ua;
    };

    const disconnect = () => {
        uaRef.current?.stop();
        uaRef.current = null;
        setStatus("disconnected");
    };

    const answer = () => {
        if (!incoming) return;
        incoming.answer({ mediaConstraints: { audio: true, video: false } });
        attachRemoteAudio(incoming);
        setActive(incoming);
        setIncoming(null);
        if (handoff) {
            enterpriseApi.acceptHandoff(handoff.id).then(setHandoff).catch(() => undefined);
        }
    };

    const hangup = () => {
        (active ?? incoming)?.terminate();
        setActive(null);
        setIncoming(null);
    };

    const toggleMute = () => {
        if (!active) return;
        if (muted) active.unmute({ audio: true });
        else active.mute({ audio: true });
        setMuted(!muted);
    };

    // *45 / *46 feature codes pause/unpause this agent in all of its queues.
    const togglePause = () => {
        const ua = uaRef.current;
        if (!ua) return;
        const code = paused ? "*46" : "*45";
        ua.call(`sip:${code}@${realm}`, { mediaConstraints: { audio: true, video: false } });
        setPaused(!paused);
        toast.success(paused ? "Vous recevez à nouveau des appels." : "Pause : aucun appel ne vous sera distribué.");
    };

    const statusBadge = {
        disconnected: <Badge variant="secondary">Hors ligne</Badge>,
        connecting: <Badge variant="secondary">Connexion…</Badge>,
        registered: <Badge>{paused ? "En pause" : "Disponible"}</Badge>,
        error: <Badge variant="destructive">Erreur</Badge>,
    }[status];

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-3">
                    <Headphones className="h-5 w-5" />
                    Mon softphone — poste {seat.extension}
                    {statusBadge}
                </CardTitle>
                <CardDescription>
                    Recevez les appels transférés par les agents IA et ceux de vos files d&apos;attente
                    ({seat.queues.length ? seat.queues.join(", ") : "aucune file"}).
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <audio ref={audioRef} autoPlay />
                {callbackCall && (incoming || active) && (
                    <div className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-4 py-3 text-sm">
                        <span className="font-medium">Rappel client</span> — décrochez : NIMBORA compose ensuite le
                        numéro de {peer}. Indiquez le résultat dans la liste des rappels une fois l&apos;appel
                        terminé.
                    </div>
                )}
                {handoff && (incoming || active) && <HandoffCard handoff={handoff} />}
                {status !== "registered" ? (
                    <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                            <Label htmlFor="sip-password">Mot de passe SIP du poste</Label>
                            <Input
                                id="sip-password"
                                type="password"
                                autoComplete="off"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="w-72"
                            />
                        </div>
                        <Button onClick={connect} disabled={status === "connecting"}>
                            <Phone className="mr-2 h-4 w-4" />
                            Se connecter
                        </Button>
                    </div>
                ) : (
                    <div className="flex flex-wrap items-center gap-3">
                        {incoming && (
                            <>
                                <span className="font-medium">Appel entrant : {peer}</span>
                                <Button onClick={answer}>
                                    <Phone className="mr-2 h-4 w-4" />
                                    Répondre
                                </Button>
                                <Button variant="destructive" onClick={hangup}>
                                    <PhoneOff className="mr-2 h-4 w-4" />
                                    Refuser
                                </Button>
                            </>
                        )}
                        {active && (
                            <>
                                <span className="font-medium">En ligne avec {peer}</span>
                                <Button variant="outline" onClick={toggleMute}>
                                    {muted ? <MicOff className="mr-2 h-4 w-4" /> : <Mic className="mr-2 h-4 w-4" />}
                                    {muted ? "Réactiver le micro" : "Couper le micro"}
                                </Button>
                                <Button variant="destructive" onClick={hangup}>
                                    <PhoneOff className="mr-2 h-4 w-4" />
                                    Raccrocher
                                </Button>
                            </>
                        )}
                        {!incoming && !active && (
                            <>
                                <span className="text-muted-foreground">En attente d&apos;appels…</span>
                                <Button variant="outline" onClick={togglePause}>
                                    {paused ? <Play className="mr-2 h-4 w-4" /> : <Pause className="mr-2 h-4 w-4" />}
                                    {paused ? "Reprendre" : "Pause"}
                                </Button>
                                <Button variant="ghost" onClick={disconnect}>
                                    Se déconnecter
                                </Button>
                            </>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}

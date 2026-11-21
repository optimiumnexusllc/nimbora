import { ArrowRightLeft, Grid3x3, Mic, MicOff, Pause, Phone, PhoneOff, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { formatDuration, initials, isDialable } from "../lib/format";
import type { HandoffCard } from "../lib/api";
import type { Call } from "../lib/phone";
import { HandoffPanel } from "./HandoffPanel";
import { Keypad } from "./Dialpad";

const STATUS: Record<Call["status"], string> = {
    ringing: "Appel entrant",
    calling: "Appel en cours…",
    early: "Ça sonne…",
    active: "",
    ended: "Appel terminé",
};

export function useTicker(active: boolean): number {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!active) return;
        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
    }, [active]);
    return now;
}

export function CallScreen({
    call,
    onAnswer,
    onDecline,
    onHangup,
    onMute,
    onHold,
    onDtmf,
    onTransfer,
    canTransfer,
    contactName,
    handoff,
}: {
    call: Call;
    onAnswer: () => void;
    onDecline: () => void;
    onHangup: () => void;
    onMute: () => void;
    onHold: () => void;
    onDtmf: (tone: string) => void;
    onTransfer: (target: string) => void;
    canTransfer: boolean;
    contactName?: string | null;
    handoff?: HandoffCard | null;
}) {
    const [panel, setPanel] = useState<"none" | "keypad" | "transfer">("none");
    const [tones, setTones] = useState("");
    const [target, setTarget] = useState("");
    const now = useTicker(call.status === "active");
    // A caller sent by the AI shows as "IA · <name>": the card's name is nicer.
    const name = handoff?.customer_name || contactName || call.name || null;
    const elapsed = call.startedAt ? formatDuration((now - call.startedAt) / 1000) : null;

    return (
        <div className={`call-screen ${call.status}`} role="dialog" aria-label="Appel">
            <div className="caller">
                <div className="avatar" aria-hidden>
                    {initials(name || call.number)}
                </div>
                <h2>{name || call.number || "Numéro masqué"}</h2>
                {name && <p className="muted number">{call.number}</p>}
                <p className="call-status" data-testid="call-status">
                    {call.status === "active" ? (call.held ? `En attente · ${elapsed}` : elapsed) : call.status === "ended" && call.endReason ? call.endReason : STATUS[call.status]}
                </p>
            </div>

            {handoff && call.status !== "ended" && <HandoffPanel card={handoff} />}

            {panel === "keypad" && call.status === "active" && (
                <div className="panel">
                    <p className="tones" aria-label="Touches envoyées">
                        {tones || " "}
                    </p>
                    <Keypad
                        onKey={(key) => {
                            if (key === "+") return;
                            setTones((t) => t + key);
                            onDtmf(key);
                        }}
                    />
                </div>
            )}
            {panel === "transfer" && call.status === "active" && (
                <form
                    className="panel transfer"
                    onSubmit={(e) => {
                        e.preventDefault();
                        if (isDialable(target)) {
                            onTransfer(target);
                            setPanel("none");
                        }
                    }}
                >
                    <label>
                        <span>Transférer vers</span>
                        <input name="transfer" inputMode="tel" autoFocus placeholder="Poste ou numéro" value={target} onChange={(e) => setTarget(e.target.value)} />
                    </label>
                    <button type="submit" className="primary" disabled={!isDialable(target)}>
                        <ArrowRightLeft size={18} /> Transférer
                    </button>
                </form>
            )}

            {call.status === "ringing" ? (
                <div className="answer-row">
                    <button type="button" className="round danger" aria-label="Refuser" onClick={onDecline}>
                        <PhoneOff size={30} />
                    </button>
                    <button type="button" className="round success pulse" aria-label="Décrocher" onClick={onAnswer}>
                        <Phone size={30} />
                    </button>
                </div>
            ) : call.status === "ended" ? null : (
                <>
                    <div className="controls">
                        <button type="button" className={`control ${call.muted ? "on" : ""}`} aria-pressed={call.muted} disabled={call.status !== "active"} onClick={onMute}>
                            {call.muted ? <MicOff size={24} /> : <Mic size={24} />}
                            <span>{call.muted ? "Micro coupé" : "Micro"}</span>
                        </button>
                        <button type="button" className={`control ${call.held ? "on" : ""}`} aria-pressed={call.held} disabled={call.status !== "active"} onClick={onHold}>
                            {call.held ? <Play size={24} /> : <Pause size={24} />}
                            <span>{call.held ? "Reprendre" : "Attente"}</span>
                        </button>
                        <button
                            type="button"
                            className={`control ${panel === "keypad" ? "on" : ""}`}
                            disabled={call.status !== "active"}
                            onClick={() => setPanel(panel === "keypad" ? "none" : "keypad")}
                        >
                            <Grid3x3 size={24} />
                            <span>Clavier</span>
                        </button>
                        {canTransfer && (
                            <button
                                type="button"
                                className={`control ${panel === "transfer" ? "on" : ""}`}
                                disabled={call.status !== "active"}
                                onClick={() => setPanel(panel === "transfer" ? "none" : "transfer")}
                            >
                                <ArrowRightLeft size={24} />
                                <span>Transférer</span>
                            </button>
                        )}
                    </div>
                    <button type="button" className="round danger hangup" aria-label="Raccrocher" onClick={onHangup}>
                        <PhoneOff size={30} />
                    </button>
                </>
            )}
        </div>
    );
}

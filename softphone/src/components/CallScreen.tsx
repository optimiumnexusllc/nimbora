import { ArrowLeftRight, ArrowRightLeft, Grid3x3, LogOut, Mic, MicOff, Pause, Phone, PhoneCall, PhoneOff, Play, Users, X } from "lucide-react";
import { useEffect, useState } from "react";

import { formatDuration, initials, isDialable } from "../lib/format";
import type { HandoffCard, Presence } from "../lib/api";
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

export type Colleague = { name: string; extension: string; presence?: Presence };

function ConsultCard({ call, held, conference }: { call: Call; held: boolean; conference: boolean }) {
    const now = useTicker(call.status === "active");
    const elapsed = call.startedAt ? formatDuration((now - call.startedAt) / 1000) : "";
    const status = conference ? `En conférence · ${elapsed}` : call.status === "active" ? (held ? `En attente · ${elapsed}` : elapsed) : STATUS[call.status];
    return (
        <div className={`consult-card ${held && !conference ? "held" : ""}`} data-testid="consult">
            <span className="avatar small">{initials(call.name || call.number)}</span>
            <span className="row-main">
                <span>{call.name || call.number}</span>
                <span className="tiny muted">{status}</span>
            </span>
        </div>
    );
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
    consult = null,
    conference = false,
    notice = null,
    colleagues = [],
    onConsult,
    onSwap,
    onCompleteTransfer,
    onCancelConsult,
    onConference,
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
    /** The colleague consulted while the customer waits. */
    consult?: Call | null;
    conference?: boolean;
    notice?: string | null;
    /** Suggested for a transfer: colleagues and their presence. */
    colleagues?: Colleague[];
    onConsult?: (target: string) => void;
    onSwap?: () => void;
    onCompleteTransfer?: () => void;
    onCancelConsult?: () => void;
    onConference?: () => void;
}) {
    const [panel, setPanel] = useState<"none" | "keypad" | "transfer">("none");
    const [tones, setTones] = useState("");
    const [target, setTarget] = useState("");
    const now = useTicker(call.status === "active");
    // A caller sent by the AI shows as "IA · <name>": the card's name is nicer.
    const name = handoff?.customer_name || contactName || call.name || null;
    const elapsed = call.startedAt ? formatDuration((now - call.startedAt) / 1000) : null;
    const consulting = !!consult && consult.status !== "ended";
    // During a consultation the microphone button acts on the colleague's call.
    const muted = consulting && !conference && consult ? consult.muted : call.muted;
    const suggestions = colleagues.filter((c) => c.presence?.state === "available").slice(0, 6);
    const chooseTarget = (extension: string) => setTarget(extension);

    return (
        <div className={`call-screen ${call.status}`} role="dialog" aria-label="Appel">
            <div className="caller">
                <div className="avatar" aria-hidden>
                    {initials(name || call.number)}
                </div>
                <h2>{name || call.number || "Numéro masqué"}</h2>
                {name && <p className="muted number">{call.number}</p>}
                <p className="call-status" data-testid="call-status">
                    {conference
                        ? `Conférence à trois · ${elapsed}`
                        : call.status === "active"
                          ? call.held
                              ? `En attente · ${elapsed}`
                              : elapsed
                          : call.status === "ended" && call.endReason
                            ? call.endReason
                            : STATUS[call.status]}
                </p>
                {notice && (
                    <p className="tiny notice" role="status">
                        {notice}
                    </p>
                )}
            </div>

            {consulting && consult && <ConsultCard call={consult} held={!!consult.held} conference={conference} />}

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
            {panel === "transfer" && call.status === "active" && !consulting && (
                <form
                    className="panel transfer"
                    onSubmit={(e) => {
                        e.preventDefault();
                        if (!isDialable(target)) return;
                        // Enter calls the colleague first: the safer choice.
                        if (onConsult) onConsult(target);
                        else onTransfer(target);
                        setPanel("none");
                    }}
                >
                    <label>
                        <span>Transférer vers</span>
                        <input name="transfer" inputMode="tel" autoFocus placeholder="Poste ou numéro" value={target} onChange={(e) => setTarget(e.target.value)} />
                    </label>
                    {suggestions.length > 0 && (
                        <div className="chips" aria-label="Collègues disponibles">
                            {suggestions.map((c) => (
                                <button key={c.extension} type="button" className={`chip ${target === c.extension ? "on" : ""}`} onClick={() => chooseTarget(c.extension)}>
                                    <span className="presence-dot available inline" aria-hidden /> {c.name} · {c.extension}
                                </button>
                            ))}
                        </div>
                    )}
                    <div className="transfer-actions">
                        {onConsult && (
                            <button type="submit" className="primary" disabled={!isDialable(target)}>
                                <PhoneCall size={18} /> Appeler d&apos;abord
                            </button>
                        )}
                        <button
                            type="button"
                            className={onConsult ? "secondary" : "primary"}
                            disabled={!isDialable(target)}
                            onClick={() => {
                                onTransfer(target);
                                setPanel("none");
                            }}
                        >
                            <ArrowRightLeft size={18} /> Transférer directement
                        </button>
                    </div>
                </form>
            )}

            {consulting && call.status === "active" && (
                <div className="consult-actions" role="group" aria-label="Consultation">
                    {!conference && (
                        <button type="button" className="control" disabled={consult?.status !== "active"} onClick={onSwap}>
                            <ArrowLeftRight size={22} />
                            <span>Basculer</span>
                        </button>
                    )}
                    <button type="button" className="control" onClick={onCompleteTransfer}>
                        {conference ? <LogOut size={22} /> : <ArrowRightLeft size={22} />}
                        <span>{conference ? "Se retirer" : "Transférer"}</span>
                    </button>
                    {!conference && (
                        <button type="button" className="control" disabled={consult?.status !== "active"} onClick={onConference}>
                            <Users size={22} />
                            <span>Conférence</span>
                        </button>
                    )}
                    {!conference && (
                        <button type="button" className="control" onClick={onCancelConsult}>
                            <X size={22} />
                            <span>Annuler</span>
                        </button>
                    )}
                </div>
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
                        <button type="button" className={`control ${muted ? "on" : ""}`} aria-pressed={muted} disabled={call.status !== "active"} onClick={onMute}>
                            {muted ? <MicOff size={24} /> : <Mic size={24} />}
                            <span>{muted ? "Micro coupé" : "Micro"}</span>
                        </button>
                        <button type="button" className={`control ${call.held ? "on" : ""}`} aria-pressed={call.held} disabled={call.status !== "active" || consulting} onClick={onHold}>
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
                                disabled={call.status !== "active" || consulting}
                                onClick={() => setPanel(panel === "transfer" ? "none" : "transfer")}
                            >
                                <ArrowRightLeft size={24} />
                                <span>Transférer</span>
                            </button>
                        )}
                    </div>
                    <button
                        type="button"
                        className="round danger hangup"
                        aria-label={consulting && !conference ? "Raccrocher avec le collègue" : conference ? "Tout raccrocher" : "Raccrocher"}
                        onClick={consulting && !conference && onCancelConsult ? onCancelConsult : onHangup}
                    >
                        <PhoneOff size={30} />
                    </button>
                </>
            )}
        </div>
    );
}

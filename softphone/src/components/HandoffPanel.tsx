import { Bot, ChevronDown, ListChecks } from "lucide-react";
import { useState } from "react";

import type { HandoffCard } from "../lib/api";

const MOOD: Record<NonNullable<HandoffCard["sentiment"]>, string> = {
    positive: "Satisfait",
    neutral: "Neutre",
    frustrated: "Agacé",
    angry: "En colère",
};

function label(key: string): string {
    const text = key.replace(/[_-]+/g, " ").trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function value(raw: unknown): string {
    if (raw === null || raw === undefined || raw === "") return "—";
    if (typeof raw === "object") return JSON.stringify(raw);
    return String(raw);
}

/** The AI's handoff card: shown while the call rings and during the call. */
export function HandoffPanel({ card }: { card: HandoffCard }) {
    const [transcript, setTranscript] = useState(false);
    const data = Object.entries(card.collected_data ?? {}).slice(0, 8);
    const pending = card.summary_status === "pending" && !card.summary;

    return (
        <section className="handoff" aria-label="Fiche de l'agent IA" data-testid="handoff-panel">
            <header>
                <Bot size={16} />
                <span>Transféré par l&apos;agent IA</span>
                {card.sentiment && <span className={`mood ${card.sentiment}`}>{MOOD[card.sentiment]}</span>}
            </header>
            {card.reason && <p className="reason">{card.reason}</p>}
            {card.summary ? <p className="summary">{card.summary}</p> : pending ? <p className="summary muted">Résumé en cours…</p> : null}
            {card.next_step && (
                <p className="next">
                    <ListChecks size={14} /> {card.next_step}
                </p>
            )}
            {data.length > 0 && (
                <dl>
                    {data.map(([key, raw]) => (
                        <div key={key}>
                            <dt>{label(key)}</dt>
                            <dd>{value(raw)}</dd>
                        </div>
                    ))}
                </dl>
            )}
            {card.transcript?.length > 0 && (
                <>
                    <button type="button" className="link" aria-expanded={transcript} onClick={() => setTranscript(!transcript)}>
                        <ChevronDown size={14} className={transcript ? "open" : ""} /> Conversation avec l&apos;IA
                    </button>
                    {transcript && (
                        <ol className="transcript">
                            {card.transcript.slice(-8).map((turn, index) => (
                                <li key={index} className={turn.speaker === "client" ? "client" : "agent"}>
                                    <strong>{turn.speaker === "client" ? "Client" : "IA"}</strong> {turn.text}
                                </li>
                            ))}
                        </ol>
                    )}
                </>
            )}
        </section>
    );
}

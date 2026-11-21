import { Delete, Phone, Voicemail } from "lucide-react";
import { useCallback, useEffect } from "react";

import { cleanNumber, isDialable } from "../lib/format";

export const KEYS: [string, string][] = [
    ["1", ""],
    ["2", "ABC"],
    ["3", "DEF"],
    ["4", "GHI"],
    ["5", "JKL"],
    ["6", "MNO"],
    ["7", "PQRS"],
    ["8", "TUV"],
    ["9", "WXYZ"],
    ["*", ""],
    ["0", "+"],
    ["#", ""],
];

export function Keypad({ onKey }: { onKey: (key: string) => void }) {
    return (
        <div className="keypad" role="group" aria-label="Clavier">
            {KEYS.map(([key, letters]) => (
                <button
                    key={key}
                    type="button"
                    className="key"
                    aria-label={key}
                    onClick={() => onKey(key)}
                    onContextMenu={(e) => {
                        // Long press 0 → "+" (international).
                        if (key === "0") {
                            e.preventDefault();
                            onKey("+");
                        }
                    }}
                >
                    <span className="digit">{key}</span>
                    <span className="letters">{letters}</span>
                </button>
            ))}
        </div>
    );
}

export function Dialpad({
    value,
    onChange,
    onCall,
    disabled,
    voicemailCode,
}: {
    value: string;
    onChange: (value: string) => void;
    onCall: (number: string) => void;
    disabled: boolean;
    voicemailCode?: string;
}) {
    const call = useCallback(() => {
        if (!disabled && isDialable(value)) onCall(cleanNumber(value));
    }, [disabled, value, onCall]);

    // Physical keyboard on desktop.
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            const target = e.target as HTMLElement | null;
            if (target && ["INPUT", "TEXTAREA"].includes(target.tagName) && target.getAttribute("name") !== "dial") return;
            if (/^[0-9*#+]$/.test(e.key) && target?.getAttribute("name") !== "dial") onChange(value + e.key);
            else if (e.key === "Backspace" && target?.getAttribute("name") !== "dial") onChange(value.slice(0, -1));
            else if (e.key === "Enter") call();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [value, onChange, call]);

    return (
        <section className="dialpad">
            <div className="display">
                <input
                    name="dial"
                    aria-label="Numéro à appeler"
                    inputMode="tel"
                    placeholder="Numéro ou poste"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                />
                {value && (
                    <button type="button" className="ghost icon" aria-label="Effacer" onClick={() => onChange(value.slice(0, -1))}>
                        <Delete size={22} />
                    </button>
                )}
            </div>
            <Keypad onKey={(key) => onChange(value + key)} />
            <div className="dial-actions">
                {voicemailCode ? (
                    <button type="button" className="ghost icon" aria-label="Messagerie vocale" disabled={disabled} onClick={() => onCall(voicemailCode)}>
                        <Voicemail size={22} />
                    </button>
                ) : (
                    <span />
                )}
                <button type="button" className="call-button" aria-label="Appeler" disabled={disabled || !isDialable(value)} onClick={call}>
                    <Phone size={28} />
                </button>
                <span />
            </div>
        </section>
    );
}

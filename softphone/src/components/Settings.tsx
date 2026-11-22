import { BellOff, CircleDot, Headphones, LogOut, PhoneForwarded, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import type { Presence, SoftphoneConfig, Status } from "../lib/api";
import { APP_VERSION } from "../lib/api";
import { isDialable } from "../lib/format";

type Device = { deviceId: string; label: string };
type Settable = "available" | "away" | "offline";
const CHOICES: [Settable, string][] = [
    ["available", "Disponible"],
    ["away", "Absent"],
    ["offline", "Hors ligne"],
];

export function Settings({
    config,
    status,
    presence,
    onSaveStatus,
    onSavePresence,
    onOutputDevice,
    onSignOut,
}: {
    config: SoftphoneConfig;
    status: Status | null;
    /** The employee's presence as colleagues see it (undefined: not known). */
    presence?: Presence;
    onSaveStatus: (dnd: boolean, forwardEnabled: boolean, forwardTo: string) => Promise<void>;
    onSavePresence?: (state: Settable, message: string) => Promise<void>;
    onOutputDevice: (deviceId: string) => void;
    onSignOut: () => void;
}) {
    const [forwardTo, setForwardTo] = useState(status?.forward.destination ?? "");
    const [outputs, setOutputs] = useState<Device[]>([]);
    const [output, setOutput] = useState("default");
    const [saving, setSaving] = useState(false);

    useEffect(() => setForwardTo(status?.forward.destination ?? ""), [status?.forward.destination]);
    const [message, setMessage] = useState(presence?.status ?? "");
    useEffect(() => setMessage(presence?.status ?? ""), [presence?.status]);
    const chosen: Settable | null =
        presence?.state === "away" ? "away" : presence?.state === "offline" ? "offline" : presence && presence.state !== "unknown" ? "available" : null;
    const savePresence = async (state: Settable) => {
        if (!onSavePresence) return;
        setSaving(true);
        try {
            await onSavePresence(state, message);
        } finally {
            setSaving(false);
        }
    };

    useEffect(() => {
        void navigator.mediaDevices
            ?.enumerateDevices?.()
            .then((devices) =>
                setOutputs(
                    devices
                        .filter((d) => d.kind === "audiooutput")
                        .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Sortie audio ${i + 1}` })),
                ),
            )
            .catch(() => undefined);
    }, []);

    const save = async (dnd: boolean, forwardEnabled: boolean) => {
        setSaving(true);
        try {
            await onSaveStatus(dnd, forwardEnabled, forwardTo);
        } finally {
            setSaving(false);
        }
    };

    return (
        <section className="list-page settings">
            <header className="list-header">
                <h2>Réglages</h2>
            </header>
            {onSavePresence && presence && presence.state !== "unknown" && (
                <div className="card" data-testid="my-presence">
                    <span>
                        <CircleDot size={18} /> Ma présence <span className="tiny muted">· vue par vos collègues : {presence.label}</span>
                    </span>
                    <div className="status-row">
                        {CHOICES.map(([state, label]) => (
                            <button key={state} type="button" aria-pressed={chosen === state} disabled={saving} onClick={() => void savePresence(state)}>
                                {label}
                            </button>
                        ))}
                    </div>
                    <input
                        aria-label="Message de présence"
                        placeholder="Message (ex. En réunion jusqu'à 15 h)"
                        maxLength={128}
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        onBlur={() => chosen && message !== (presence.status ?? "") && void savePresence(chosen)}
                    />
                </div>
            )}
            <div className="card">
                <label className="toggle">
                    <span>
                        <BellOff size={18} /> Ne pas déranger
                        <span className="tiny muted block">Vos appels suivent la règle « sans réponse » du PBX.</span>
                    </span>
                    <input
                        type="checkbox"
                        role="switch"
                        aria-label="Ne pas déranger"
                        disabled={!status || saving}
                        checked={status?.dnd ?? false}
                        onChange={(e) => void save(e.target.checked, status?.forward.enabled ?? false)}
                    />
                </label>
                <label className="toggle">
                    <span>
                        <PhoneForwarded size={18} /> Renvoyer tous mes appels
                    </span>
                    <input
                        type="checkbox"
                        role="switch"
                        aria-label="Renvoyer tous mes appels"
                        disabled={!status || saving || (!status?.forward.enabled && !isDialable(forwardTo))}
                        checked={status?.forward.enabled ?? false}
                        onChange={(e) => void save(status?.dnd ?? false, e.target.checked)}
                    />
                </label>
                <input
                    aria-label="Numéro de renvoi"
                    inputMode="tel"
                    placeholder="Numéro ou poste"
                    value={forwardTo}
                    disabled={status?.forward.enabled}
                    onChange={(e) => setForwardTo(e.target.value)}
                />
            </div>
            {outputs.length > 1 && (
                <div className="card">
                    <label>
                        <span>
                            <Headphones size={18} /> Sortie audio
                        </span>
                        <select
                            aria-label="Sortie audio"
                            value={output}
                            onChange={(e) => {
                                setOutput(e.target.value);
                                onOutputDevice(e.target.value);
                            }}
                        >
                            {outputs.map((d) => (
                                <option key={d.deviceId} value={d.deviceId}>
                                    {d.label}
                                </option>
                            ))}
                        </select>
                    </label>
                </div>
            )}
            <div className="card about">
                <p>
                    <ShieldCheck size={16} /> {config.account.display_name} · poste {config.account.extension ?? "—"}
                </p>
                <p className="tiny muted">
                    {config.device.name} · {config.brand.pbx_name} · version {APP_VERSION}
                </p>
                <p className="tiny muted">Connexion chiffrée (WSS, SRTP). Le mot de passe SIP n&apos;est jamais enregistré sur l&apos;appareil.</p>
            </div>
            <button type="button" className="danger-outline" onClick={onSignOut}>
                <LogOut size={18} /> Déconnecter cet appareil
            </button>
        </section>
    );
}

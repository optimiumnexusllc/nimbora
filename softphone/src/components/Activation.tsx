import { KeyRound, Loader2, Server, Smartphone } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, SoftphoneApi, type SoftphoneConfig } from "../lib/api";
import { detectPlatform, formatCode, normalizeCode, normalizeServer, PLATFORM_LABELS } from "../lib/format";

export type Paired = { server: string; token: string; deviceName: string; config: SoftphoneConfig };

export function Activation({
    initial,
    onPaired,
    makeApi = (server) => new SoftphoneApi(server),
}: {
    initial?: { server?: string | null; code?: string | null };
    onPaired: (paired: Paired) => void;
    makeApi?: (server: string) => SoftphoneApi;
}) {
    const platform = detectPlatform();
    const [server, setServer] = useState(initial?.server ?? "");
    const [code, setCode] = useState(initial?.code ? formatCode(initial.code) : "");
    const [deviceName, setDeviceName] = useState(`Softphone ${PLATFORM_LABELS[platform]}`);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (initial?.server) setServer(initial.server);
        if (initial?.code) setCode(formatCode(initial.code));
    }, [initial?.server, initial?.code]);

    const ready = server.trim().length > 3 && normalizeCode(code).length === 8;

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (!ready) return;
        setBusy(true);
        setError(null);
        try {
            const base = normalizeServer(server);
            const api = makeApi(base);
            const result = await api.activate(normalizeCode(code), deviceName.trim() || "Softphone", platform);
            onPaired({ server: base, token: result.token, deviceName, config: result.config });
        } catch (e) {
            setError(e instanceof ApiError ? e.message : "Adresse du serveur invalide");
        } finally {
            setBusy(false);
        }
    };

    return (
        <main className="pairing">
            <div className="logo" aria-hidden>
                <img src="./icon.svg" alt="" width={72} height={72} />
            </div>
            <h1>NIMBORA Softphone</h1>
            <p className="muted">
                Votre poste d&apos;entreprise sur cet appareil. Demandez à votre administrateur un code d&apos;activation
                (Téléphonie d&apos;entreprise → Postes → Softphone), ou scannez le QR code affiché.
            </p>
            <form onSubmit={submit} className="card form">
                <label>
                    <span>
                        <Server size={16} /> Adresse de la plateforme
                    </span>
                    <input
                        name="server"
                        inputMode="url"
                        autoComplete="url"
                        placeholder="nimbora.votre-entreprise.com"
                        value={server}
                        onChange={(e) => setServer(e.target.value)}
                    />
                </label>
                <label>
                    <span>
                        <KeyRound size={16} /> Code d&apos;activation
                    </span>
                    <input
                        name="code"
                        className="code"
                        autoCapitalize="characters"
                        autoComplete="one-time-code"
                        placeholder="ABCD-2345"
                        value={code}
                        onChange={(e) => setCode(formatCode(e.target.value))}
                    />
                </label>
                <label>
                    <span>
                        <Smartphone size={16} /> Nom de cet appareil
                    </span>
                    <input name="device" value={deviceName} maxLength={128} onChange={(e) => setDeviceName(e.target.value)} />
                </label>
                {error && (
                    <p className="error" role="alert">
                        {error}
                    </p>
                )}
                <button type="submit" className="primary" disabled={!ready || busy}>
                    {busy ? <Loader2 className="spin" size={18} /> : null} Activer
                </button>
            </form>
            <p className="tiny muted">Le code ne sert qu&apos;une fois et expire après 15 minutes.</p>
        </main>
    );
}

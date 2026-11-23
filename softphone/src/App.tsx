import { BellOff, Clock, Grid3x3, Loader2, Settings as SettingsIcon, Users, WifiOff } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Activation, type Paired } from "./components/Activation";
import { CallScreen } from "./components/CallScreen";
import { Dialpad } from "./components/Dialpad";
import { Contacts, Recents } from "./components/Lists";
import { Settings } from "./components/Settings";
import { ApiError, type Directory, forget, type HandoffCard, loadSaved, type ParkedCall, type RecentCall, save, SoftphoneApi, type SoftphoneConfig, type Status } from "./lib/api";
import { parsePairingLink, type PairingLink } from "./lib/format";
import { notify, onPairingLink, Ringtone } from "./lib/native";
import { AUTH_REFUSED, Phone, type Snapshot } from "./lib/phone";

type Tab = "dial" | "recents" | "contacts" | "settings";
type Session = { api: SoftphoneApi; config: SoftphoneConfig; deviceName: string };

const REGISTRATION: Record<Snapshot["registration"], string> = {
    disconnected: "Hors ligne",
    connecting: "Connexion…",
    registered: "Disponible",
    failed: "Non connecté",
};

// Module-level so its identity is stable: an inline default would change on
// every render, re-run boot() and rebuild the SIP agent in a loop.
const defaultMakeApi = (server: string, token?: string) => new SoftphoneApi(server, token ?? null);

export function App({ makeApi = defaultMakeApi }: { makeApi?: (server: string, token?: string) => SoftphoneApi }) {
    const [session, setSession] = useState<Session | null>(null);
    const [booting, setBooting] = useState(true);
    const [bootError, setBootError] = useState<string | null>(null);
    const [pairing, setPairing] = useState<PairingLink | null>(null);
    const [snapshot, setSnapshot] = useState<Snapshot>({ registration: "disconnected", error: null, call: null, consult: null, conference: false, notice: null });
    const [tab, setTab] = useState<Tab>("dial");
    const [dial, setDial] = useState("");
    const [recents, setRecents] = useState<RecentCall[] | null>(null);
    const [loadingRecents, setLoadingRecents] = useState(false);
    const [directory, setDirectory] = useState<Directory | null>(null);
    const [status, setStatus] = useState<Status | null>(null);
    const [handoff, setHandoff] = useState<HandoffCard | null>(null);
    const phoneRef = useRef<Phone | null>(null);
    const ringtone = useMemo(() => new Ringtone(), []);

    // Start from a saved pairing (token only: the SIP secret is fetched live).
    const boot = useCallback(async () => {
        setBootError(null);
        const saved = loadSaved();
        if (!saved) {
            setBooting(false);
            return;
        }
        const api = makeApi(saved.server, saved.token);
        try {
            const config = await api.config();
            setSession({ api, config, deviceName: saved.deviceName });
        } catch (e) {
            if (e instanceof ApiError && e.status === 401) forget();
            else setBootError(e instanceof Error ? e.message : "Démarrage impossible");
        } finally {
            setBooting(false);
        }
    }, [makeApi]);

    // Boot once: a later change of makeApi must not restart the phone.
    const booted = useRef(false);
    useEffect(() => {
        if (booted.current) return;
        booted.current = true;
        void boot();
    }, [boot]);

    useEffect(() => {
        let stop: (() => void) | undefined;
        void onPairingLink((url) => {
            const link = parsePairingLink(url);
            if (link) setPairing(link);
        }).then((unlisten) => (stop = unlisten));
        return () => stop?.();
    }, []);

    // The phone itself.
    useEffect(() => {
        if (!session) return;
        const audio = document.getElementById("remote-audio") as HTMLAudioElement | null;
        const phone = new Phone(session.config, audio);
        phone.onIncoming = (call) => void notify(`Appel de ${call.name || call.number || "numéro masqué"}`, `${session.config.brand.pbx_name} · poste ${session.config.account.extension ?? ""}`);
        phoneRef.current = phone;
        const unsubscribe = phone.subscribe(setSnapshot);
        void phone.start();
        return () => {
            unsubscribe();
            phone.stop();
            phoneRef.current = null;
        };
    }, [session]);

    // The SIP secret was changed on the PBX (« Régénérer le mot de passe SIP »):
    // the refused registration fetches the account again, once, and the phone
    // restarts with the new secret. Never in the middle of a call.
    const refetchedAfterRefusal = useRef(false);
    useEffect(() => {
        if (snapshot.registration === "registered") refetchedAfterRefusal.current = false;
        if (!session || snapshot.error !== AUTH_REFUSED || snapshot.call || refetchedAfterRefusal.current) return;
        refetchedAfterRefusal.current = true;
        void session.api
            .config()
            .then((config) => {
                if (config.account.password !== session.config.account.password || config.account.sip_identity !== session.config.account.sip_identity) {
                    setSession({ ...session, config });
                }
            })
            .catch(() => undefined);
    }, [session, snapshot.registration, snapshot.error, snapshot.call]);

    useEffect(() => {
        if (snapshot.call?.status === "ringing") ringtone.start();
        else ringtone.stop();
    }, [snapshot.call?.status, ringtone]);

    const loadRecents = useCallback(async () => {
        if (!session) return;
        setLoadingRecents(true);
        try {
            setRecents(await session.api.history());
        } catch {
            setRecents((r) => r ?? []);
        } finally {
            setLoadingRecents(false);
        }
    }, [session]);

    useEffect(() => {
        if (!session) return;
        void session.api.directory().then(setDirectory).catch(() => setDirectory({ people: [], services: [] }));
        void session.api.status().then(setStatus).catch(() => undefined);
        void loadRecents();
    }, [session, loadRecents]);

    // Parked calls, while Récents is open (they are taken by dialling the slot).
    const [parked, setParked] = useState<ParkedCall[]>([]);
    useEffect(() => {
        if (!session || tab !== "recents" || !session.config.features.parking?.length) {
            setParked([]);
            return;
        }
        const load = () =>
            void session.api
                .parked()
                .then(setParked)
                .catch(() => setParked([]));
        load();
        const timer = setInterval(load, 10_000);
        return () => clearInterval(timer);
    }, [session, tab]);

    // Colleagues' presence changes all the time: refresh while Contacts is open.
    useEffect(() => {
        if (!session || tab !== "contacts") return;
        const timer = setInterval(() => {
            void session.api
                .directory()
                .then(setDirectory)
                .catch(() => undefined);
        }, 20_000);
        return () => clearInterval(timer);
    }, [session, tab]);
    const searchCustomers = useCallback(
        async (query: string) => (session ? ((await session.api.directory(query)).customers ?? null) : null),
        [session],
    );

    // A caller handed over by the AI comes with its card: fetch it as it rings.
    const incomingId = snapshot.call?.direction === "incoming" ? snapshot.call.id : null;
    const incomingNumber = snapshot.call?.number ?? "";
    useEffect(() => {
        setHandoff(null);
        if (!incomingId || !session || !incomingNumber) return;
        let current = true;
        session.api
            .handoff(incomingNumber)
            .then((card) => current && setHandoff(card))
            .catch(() => undefined);
        return () => {
            current = false;
        };
    }, [incomingId, incomingNumber, session]);

    // Refresh the call list after each call.
    const lastStatus = useRef<string | undefined>(undefined);
    useEffect(() => {
        if (lastStatus.current && lastStatus.current !== "ended" && snapshot.call?.status === "ended") void loadRecents();
        lastStatus.current = snapshot.call?.status;
    }, [snapshot.call?.status, loadRecents]);

    const paired = (result: Paired) => {
        save({ server: result.server, token: result.token, deviceName: result.deviceName });
        setPairing(null);
        setSession({ api: makeApi(result.server, result.token), config: result.config, deviceName: result.deviceName });
    };

    const signOut = async () => {
        if (!session) return;
        if (!window.confirm("Déconnecter cet appareil ? Un nouveau code d'activation sera nécessaire.")) return;
        try {
            await session.api.signOut();
        } catch {
            // Revoked anyway from the console if the server is unreachable.
        }
        forget();
        setSession(null);
        setRecents(null);
        setDirectory(null);
        setStatus(null);
    };

    const call = (number: string) => {
        phoneRef.current?.call(number);
        setDial("");
        setTab("dial");
    };

    if (booting) {
        return (
            <main className="center">
                <Loader2 className="spin" size={32} />
            </main>
        );
    }
    if (bootError) {
        return (
            <main className="center column">
                <WifiOff size={32} />
                <p>{bootError}</p>
                <button type="button" className="primary" onClick={() => void boot()}>
                    Réessayer
                </button>
            </main>
        );
    }

    if (!session) {
        return <Activation initial={pairing ?? undefined} onPaired={paired} makeApi={(server) => makeApi(server)} />;
    }
    const { config } = session;
    const registered = snapshot.registration === "registered";
    const contactName = snapshot.call
        ? (directory?.people.find((p) => p.extension === snapshot.call?.number)?.name ??
          directory?.customers?.find((c) => c.number === snapshot.call?.number)?.name ??
          null)
        : null;
    const myPresence = directory?.people.find((p) => p.me)?.presence;

    const answer = () => {
        phoneRef.current?.answer();
        if (handoff && session) void session.api.handoffAnswered(handoff.id).catch(() => undefined);
    };

    return (
        <div className="app">
            <header className="topbar">
                <div className="who">
                    <strong>{config.account.display_name}</strong>
                    <span className="tiny muted">
                        Poste {config.account.extension ?? "—"} · {config.brand.pbx_name}
                    </span>
                </div>
                <span className={`presence ${snapshot.registration} ${status?.dnd ? "dnd" : ""}`} data-testid="registration" title={snapshot.error ?? undefined}>
                    {status?.dnd ? <BellOff size={14} /> : <span className="dot" />}
                    {status?.dnd ? "Ne pas déranger" : REGISTRATION[snapshot.registration]}
                </span>
            </header>
            {snapshot.error && snapshot.registration !== "registered" && (
                <p className="banner" role="status">
                    {snapshot.error}
                </p>
            )}

            <div className="content">
                {tab === "dial" && (
                    <Dialpad value={dial} onChange={setDial} onCall={call} disabled={!registered} voicemailCode={config.features.voicemail_code} pickupCode={config.features.pickup_code} />
                )}
                {tab === "recents" && <Recents calls={recents} loading={loadingRecents} onCall={call} onRefresh={() => void loadRecents()} parked={parked} />}
                {tab === "contacts" && <Contacts directory={directory} onCall={call} onSearchCustomers={searchCustomers} />}
                {tab === "settings" && (
                    <Settings
                        config={config}
                        status={status}
                        presence={myPresence}
                        onSavePresence={async (state, message) => {
                            try {
                                const saved = await session.api.savePresence(state, message);
                                setDirectory((d) => d && { ...d, people: d.people.map((p) => (p.me ? { ...p, presence: saved } : p)) });
                            } catch (e) {
                                window.alert(e instanceof Error ? e.message : "Enregistrement impossible");
                            }
                        }}
                        onSaveStatus={async (dnd, forwardEnabled, forwardTo) => {
                            try {
                                setStatus(await session.api.saveStatus(dnd, forwardEnabled, forwardTo));
                            } catch (e) {
                                window.alert(e instanceof Error ? e.message : "Enregistrement impossible");
                            }
                        }}
                        onOutputDevice={(id) => phoneRef.current?.setOutputDevice(id)}
                        onSignOut={() => void signOut()}
                    />
                )}
            </div>

            <nav className="tabs" aria-label="Navigation">
                {(
                    [
                        ["dial", Grid3x3, "Clavier"],
                        ["recents", Clock, "Récents"],
                        ["contacts", Users, "Contacts"],
                        ["settings", SettingsIcon, "Réglages"],
                    ] as const
                ).map(([id, Icon, label]) => (
                    <button key={id} type="button" className={tab === id ? "active" : ""} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>
                        <Icon size={22} />
                        <span>{label}</span>
                    </button>
                ))}
            </nav>

            {snapshot.call && (
                <CallScreen
                    call={snapshot.call}
                    contactName={contactName}
                    canTransfer={config.features.transfer}
                    handoff={handoff}
                    onAnswer={answer}
                    onDecline={() => phoneRef.current?.decline()}
                    onHangup={() => phoneRef.current?.hangup()}
                    onMute={() => phoneRef.current?.toggleMute()}
                    onHold={() => phoneRef.current?.toggleHold()}
                    onDtmf={(tone) => phoneRef.current?.dtmf(tone)}
                    onTransfer={(target) => phoneRef.current?.transfer(target)}
                    consult={snapshot.consult}
                    conference={snapshot.conference}
                    notice={snapshot.notice}
                    colleagues={(directory?.people ?? []).filter((p) => !p.me)}
                    parking={config.features.parking ?? []}
                    onConsult={config.features.transfer ? (target) => phoneRef.current?.consult(target) : undefined}
                    onSwap={() => phoneRef.current?.swap()}
                    onCompleteTransfer={() => phoneRef.current?.completeTransfer()}
                    onCancelConsult={() => phoneRef.current?.cancelConsult()}
                    onConference={() => void phoneRef.current?.startConference()}
                />
            )}
        </div>
    );
}

import { CircleParking, Crown, PhoneIncoming, PhoneMissed, PhoneOutgoing, RefreshCw, Search, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Customer, Directory, ParkedCall, Presence, RecentCall } from "../lib/api";
import { formatDuration, initials } from "../lib/format";

const when = (iso: string | null) => {
    if (!iso) return "";
    const date = new Date(iso);
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    return sameDay
        ? date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
};

export function Recents({
    calls,
    loading,
    onCall,
    onRefresh,
    parked = [],
}: {
    calls: RecentCall[] | null;
    loading: boolean;
    onCall: (number: string) => void;
    onRefresh: () => void;
    /** Calls waiting in a parking lot: dial the slot to take one. */
    parked?: ParkedCall[];
}) {
    return (
        <section className="list-page">
            <header className="list-header">
                <h2>Récents</h2>
                <button type="button" className="ghost icon" aria-label="Actualiser" onClick={onRefresh}>
                    <RefreshCw size={18} className={loading ? "spin" : ""} />
                </button>
            </header>
            {parked.length > 0 && (
                <>
                    <h3 className="section-title">Appels parqués</h3>
                    <ul className="list">
                        {parked.map((p) => (
                            <li key={`${p.lot}-${p.slot}`}>
                                <button type="button" className="row" onClick={() => onCall(p.slot)} data-testid="parked">
                                    <CircleParking size={18} className="muted" />
                                    <span className="row-main">
                                        <span>{p.name || p.number || "Appelant"}</span>
                                        <span className="tiny muted">
                                            Place {p.slot}
                                            {p.lot ? ` · ${p.lot}` : ""} · attend depuis {formatDuration(p.waiting_seconds)}
                                        </span>
                                    </span>
                                    <span className="mono muted">Reprendre</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                    <h3 className="section-title">Récents</h3>
                </>
            )}
            {!calls?.length ? (
                <p className="empty muted">{loading ? "Chargement…" : "Aucun appel récent."}</p>
            ) : (
                <ul className="list">
                    {calls.map((c) => {
                        const missed = c.direction === "incoming" && !c.answered;
                        const Icon = missed ? PhoneMissed : c.direction === "incoming" ? PhoneIncoming : PhoneOutgoing;
                        return (
                            <li key={c.id}>
                                <button type="button" className="row" disabled={!c.number} onClick={() => c.number && onCall(c.number)} data-testid="recent">
                                    <Icon size={18} className={missed ? "danger-text" : "muted"} />
                                    <span className="row-main">
                                        <span className={missed ? "danger-text" : ""}>{c.name || c.number || "Numéro masqué"}</span>
                                        <span className="tiny muted">
                                            {c.name ? `${c.number} · ` : ""}
                                            {missed ? "Manqué" : c.answered ? formatDuration(c.duration) : "Sans réponse"}
                                        </span>
                                    </span>
                                    <span className="tiny muted">{when(c.start)}</span>
                                </button>
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}

const fold = (text: string) =>
    text
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .toLowerCase();

function PresenceDot({ presence }: { presence?: Presence }) {
    if (!presence || presence.state === "unknown") return null;
    return <span className={`presence-dot ${presence.state}`} title={presence.label} aria-hidden />;
}

/** Colleagues (with their presence), services and customers, in one place. */
export function Contacts({
    directory,
    onCall,
    onSearchCustomers,
}: {
    directory: Directory | null;
    onCall: (number: string) => void;
    onSearchCustomers?: (query: string) => Promise<Customer[] | null>;
}) {
    const [query, setQuery] = useState("");
    const [found, setFound] = useState<Customer[] | null | undefined>(undefined);
    const q = fold(query.trim());
    const match = (text: string) => fold(text).includes(q);
    const people = useMemo(() => (directory?.people ?? []).filter((p) => !p.me && (match(p.name) || p.extension.includes(q))), [directory, q]);
    const services = useMemo(() => (directory?.services ?? []).filter((s) => match(s.name) || s.extension.includes(q)), [directory, q]);

    // Customers are searched on the server (the company may have thousands).
    useEffect(() => {
        if (!q || !onSearchCustomers) {
            setFound(undefined);
            return;
        }
        let stale = false;
        const timer = setTimeout(() => {
            void onSearchCustomers(query.trim())
                .then((customers) => !stale && setFound(customers))
                .catch(() => !stale && setFound([]));
        }, 300);
        return () => {
            stale = true;
            clearTimeout(timer);
        };
    }, [q, query, onSearchCustomers]);
    const customers = found === undefined ? directory?.customers : found;
    const available = people.filter((p) => p.presence?.state === "available").length;

    return (
        <section className="list-page">
            <header className="list-header">
                <h2>Contacts</h2>
                {directory?.presence_live && <span className="tiny muted">{available} disponible{available > 1 ? "s" : ""}</span>}
            </header>
            <label className="search">
                <Search size={16} />
                <input aria-label="Rechercher un contact" placeholder="Nom, poste ou numéro" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            {services.length > 0 && (
                <>
                    <h3 className="section-title">Services</h3>
                    <ul className="list">
                        {services.map((s) => (
                            <li key={`${s.kind}-${s.extension}`}>
                                <button type="button" className="row" onClick={() => onCall(s.extension)}>
                                    <span className="avatar small">
                                        <Users size={16} />
                                    </span>
                                    <span className="row-main">
                                        <span>{s.name}</span>
                                        <span className="tiny muted">{s.kind === "queue" ? "File d'attente" : "Groupe"}</span>
                                    </span>
                                    <span className="mono muted">{s.extension}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </>
            )}
            <h3 className="section-title">Collègues</h3>
            {!people.length ? (
                <p className="empty muted">{directory ? "Personne ne correspond." : "Chargement…"}</p>
            ) : (
                <ul className="list">
                    {people.map((p) => (
                        <li key={p.extension}>
                            <button type="button" className="row" onClick={() => onCall(p.extension)} data-testid="contact">
                                <span className="avatar small with-presence">
                                    {initials(p.name)}
                                    <PresenceDot presence={p.presence} />
                                </span>
                                <span className="row-main">
                                    <span>{p.name}</span>
                                    {p.presence && p.presence.state !== "unknown" && (
                                        <span className={`tiny presence-label ${p.presence.state}`} data-testid="presence">
                                            {p.presence.label}
                                            {p.presence.status ? ` · ${p.presence.status}` : ""}
                                        </span>
                                    )}
                                </span>
                                <span className="mono muted">{p.extension}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {customers && (
                <>
                    <h3 className="section-title">{q ? "Clients" : "Clients récents"}</h3>
                    {!customers.length ? (
                        <p className="empty muted">{q ? "Aucun client ne correspond." : "Aucun client pour l'instant."}</p>
                    ) : (
                        <ul className="list">
                            {customers.map((c) => (
                                <li key={c.id}>
                                    <button type="button" className="row" onClick={() => onCall(c.number)} data-testid="customer">
                                        <span className="avatar small customer">
                                            {c.vip ? <Crown size={16} /> : initials(c.name || "#")}
                                        </span>
                                        <span className="row-main">
                                            <span>
                                                {c.name || c.number}
                                                {c.vip && <span className="vip">VIP</span>}
                                            </span>
                                            <span className="tiny muted">
                                                {c.advisor ? `Conseiller : ${c.advisor}` : `${c.calls} appel${c.calls > 1 ? "s" : ""}`}
                                                {c.last_seen_at ? ` · ${when(c.last_seen_at)}` : ""}
                                            </span>
                                        </span>
                                        <span className="mono muted">{c.name ? c.number : ""}</span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </section>
    );
}

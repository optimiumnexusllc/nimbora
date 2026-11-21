import { PhoneIncoming, PhoneMissed, PhoneOutgoing, RefreshCw, Search, Users } from "lucide-react";
import { useMemo, useState } from "react";

import type { Directory, RecentCall } from "../lib/api";
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
}: {
    calls: RecentCall[] | null;
    loading: boolean;
    onCall: (number: string) => void;
    onRefresh: () => void;
}) {
    return (
        <section className="list-page">
            <header className="list-header">
                <h2>Récents</h2>
                <button type="button" className="ghost icon" aria-label="Actualiser" onClick={onRefresh}>
                    <RefreshCw size={18} className={loading ? "spin" : ""} />
                </button>
            </header>
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

export function Contacts({ directory, onCall }: { directory: Directory | null; onCall: (number: string) => void }) {
    const [query, setQuery] = useState("");
    const q = query
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .toLowerCase();
    const match = (text: string) =>
        text
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, "")
            .toLowerCase()
            .includes(q);
    const people = useMemo(() => (directory?.people ?? []).filter((p) => !p.me && (match(p.name) || p.extension.includes(q))), [directory, q]);
    const services = useMemo(() => (directory?.services ?? []).filter((s) => match(s.name) || s.extension.includes(q)), [directory, q]);

    return (
        <section className="list-page">
            <header className="list-header">
                <h2>Contacts</h2>
            </header>
            <label className="search">
                <Search size={16} />
                <input aria-label="Rechercher un collègue" placeholder="Nom ou poste" value={query} onChange={(e) => setQuery(e.target.value)} />
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
                                <span className="avatar small">{initials(p.name)}</span>
                                <span className="row-main">{p.name}</span>
                                <span className="mono muted">{p.extension}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

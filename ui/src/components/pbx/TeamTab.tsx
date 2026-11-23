"use client";

import { CircleParking, Megaphone, PhoneIncoming, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createPagingApiV1PbxPagingsPost,
    createParkingLotApiV1PbxParkingLotsPost,
    createPickupGroupApiV1PbxPickupGroupsPost,
    deletePagingApiV1PbxPagingsPagingIdDelete,
    deleteParkingLotApiV1PbxParkingLotsLotIdDelete,
    deletePickupGroupApiV1PbxPickupGroupsGroupIdDelete,
    listPagingsApiV1PbxPagingsGet,
    listParkedCallsApiV1PbxParkedCallsGet,
    listParkingLotsApiV1PbxParkingLotsGet,
    listPickupGroupsApiV1PbxPickupGroupsGet,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import type { PbxUser } from "./types";

type Member = { uuid: string; name: string; extension: string | null };
type PickupGroup = { id: number; name: string; members: Member[]; code: string };
type ParkingLot = { id: number; name: string; extension: string | null; slots_start: string; slots_end: string; timeout: number };
type Parked = { lot: string | null; slot: string; number: string; name: string | null; waiting_seconds: number };
type Paging = { id: number; name: string; number: string; dial: string; kind: "intercom" | "announcement"; members: Member[]; callers: Member[] };

/** Pick extensions (user uuids) with checkboxes. */
function Members({ users, value, onChange, label }: { users: PbxUser[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
    return (
        <fieldset className="space-y-1">
            <legend className="text-sm font-medium">{label}</legend>
            <div className="flex flex-wrap gap-2">
                {users
                    .filter((u) => u.extension)
                    .map((u) => {
                        const on = value.includes(u.uuid);
                        return (
                            <label key={u.uuid} className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${on ? "border-primary bg-primary/10" : "border-border/60"}`}>
                                <input type="checkbox" className="sr-only" checked={on} onChange={() => onChange(on ? value.filter((x) => x !== u.uuid) : [...value, u.uuid])} />
                                {u.extension} · {u.name}
                            </label>
                        );
                    })}
            </div>
        </fieldset>
    );
}

const names = (members: Member[]) => members.map((m) => (m.extension ? `${m.extension} · ${m.name}` : m.name)).join(", ") || "—";

/** Call pickup groups, parking lots and intercoms: working as a team on the PBX. */
export function TeamTab({ users }: { users: PbxUser[] }) {
    const [pickups, setPickups] = useState<PickupGroup[]>([]);
    const [lots, setLots] = useState<ParkingLot[]>([]);
    const [parked, setParked] = useState<Parked[]>([]);
    const [pagings, setPagings] = useState<Paging[]>([]);
    const [pickupForm, setPickupForm] = useState({ name: "", members: [] as string[] });
    const [lotForm, setLotForm] = useState({ name: "", extension: "700", slots_start: "701", slots_end: "720", timeout: 45 });
    const [pagingForm, setPagingForm] = useState({ name: "", number: "", members: [] as string[], callers: [] as string[], duplex: true });

    const load = useCallback(async () => {
        const [p, l, k, g] = await Promise.all([
            listPickupGroupsApiV1PbxPickupGroupsGet(),
            listParkingLotsApiV1PbxParkingLotsGet(),
            listParkedCallsApiV1PbxParkedCallsGet(),
            listPagingsApiV1PbxPagingsGet(),
        ]);
        if (!p.error) setPickups(p.data as unknown as PickupGroup[]);
        if (!l.error) setLots(l.data as unknown as ParkingLot[]);
        if (!k.error) setParked(k.data as unknown as Parked[]);
        if (!g.error) setPagings(g.data as unknown as Paging[]);
    }, []);

    const { user, loading: authLoading } = useAuth();
    const fetched = useRef(false);
    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        void load();
    }, [authLoading, user, load]);

    const run = async (call: Promise<{ error?: unknown }>, success: string) => {
        const response = await call;
        if (response.error) {
            toast.error(detailFromError(response.error, "Opération impossible"));
            return false;
        }
        toast.success(success);
        void load();
        return true;
    };

    return (
        <div className="space-y-6" data-testid="team-tab">
            <PageSection
                title="Interception d'appel"
                description="Les membres d'un groupe décrochent un appel qui sonne chez un collègue du groupe en composant *8 (bouton « Intercepter » du Softphone)."
                actions={
                    <Button variant="ghost" size="icon" aria-label="Actualiser" onClick={() => void load()}>
                        <RefreshCw />
                    </Button>
                }
            >
                <ul className="mb-4 space-y-2">
                    {pickups.map((g) => (
                        <li key={g.id} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3 text-sm" data-testid="pickup-group">
                            <span>
                                <PhoneIncoming className="mr-2 inline size-4" />
                                <strong>{g.name}</strong> <span className="text-muted-foreground">· {names(g.members)}</span>
                            </span>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Supprimer le groupe ${g.name}`}
                                onClick={() => window.confirm(`Supprimer le groupe « ${g.name} » ?`) && void run(deletePickupGroupApiV1PbxPickupGroupsGroupIdDelete({ path: { group_id: g.id } }), "Groupe supprimé")}
                            >
                                <Trash2 />
                            </Button>
                        </li>
                    ))}
                </ul>
                <div className="space-y-3 rounded-lg bg-muted/30 p-3">
                    <div className="space-y-1">
                        <Label htmlFor="pickup-name">Nouveau groupe</Label>
                        <Input id="pickup-name" placeholder="ex. Accueil" value={pickupForm.name} onChange={(e) => setPickupForm({ ...pickupForm, name: e.target.value })} />
                    </div>
                    <Members users={users} label="Membres (au moins deux)" value={pickupForm.members} onChange={(members) => setPickupForm({ ...pickupForm, members })} />
                    <Button
                        disabled={!pickupForm.name.trim() || pickupForm.members.length < 2}
                        onClick={async () => {
                            if (await run(createPickupGroupApiV1PbxPickupGroupsPost({ body: pickupForm }), "Groupe d'interception créé")) setPickupForm({ name: "", members: [] });
                        }}
                    >
                        <Plus /> Créer le groupe
                    </Button>
                </div>
            </PageSection>

            <PageSection title="Parcage" description="Transférez un appel vers le numéro du parking : il attend sur une place (701, 702…) et n'importe qui le reprend en composant cette place. S'il attend trop, il rappelle l'employé.">
                {parked.length > 0 && (
                    <div className="mb-4 rounded-lg border border-amber-500/40 p-3 text-sm" data-testid="parked-calls">
                        <p className="mb-1 font-medium">Appels parqués</p>
                        {parked.map((p) => (
                            <p key={`${p.lot}-${p.slot}`}>
                                <Badge variant="outline">Place {p.slot}</Badge> {p.name || p.number} · {Math.floor(p.waiting_seconds / 60)} min {p.waiting_seconds % 60} s{p.lot ? ` · ${p.lot}` : ""}
                            </p>
                        ))}
                    </div>
                )}
                <ul className="mb-4 space-y-2">
                    {lots.map((lot) => (
                        <li key={lot.id} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3 text-sm" data-testid="parking-lot">
                            <span>
                                <CircleParking className="mr-2 inline size-4" />
                                <strong>{lot.name}</strong> · numéro <span className="font-mono">{lot.extension}</span> · places{" "}
                                <span className="font-mono">
                                    {lot.slots_start}–{lot.slots_end}
                                </span>{" "}
                                · rappel après {lot.timeout} s
                            </span>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Supprimer le parking ${lot.name}`}
                                onClick={() => window.confirm(`Supprimer « ${lot.name} » ?`) && void run(deleteParkingLotApiV1PbxParkingLotsLotIdDelete({ path: { lot_id: lot.id } }), "Parking supprimé")}
                            >
                                <Trash2 />
                            </Button>
                        </li>
                    ))}
                </ul>
                <div className="grid gap-3 rounded-lg bg-muted/30 p-3 sm:grid-cols-5 sm:items-end">
                    <div className="space-y-1 sm:col-span-2">
                        <Label htmlFor="lot-name">Nom</Label>
                        <Input id="lot-name" placeholder="ex. Accueil" value={lotForm.name} onChange={(e) => setLotForm({ ...lotForm, name: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="lot-extension">Numéro</Label>
                        <Input id="lot-extension" inputMode="numeric" value={lotForm.extension} onChange={(e) => setLotForm({ ...lotForm, extension: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="lot-start">Places de… à…</Label>
                        <div className="flex gap-1">
                            <Input id="lot-start" aria-label="Première place" inputMode="numeric" value={lotForm.slots_start} onChange={(e) => setLotForm({ ...lotForm, slots_start: e.target.value })} />
                            <Input aria-label="Dernière place" inputMode="numeric" value={lotForm.slots_end} onChange={(e) => setLotForm({ ...lotForm, slots_end: e.target.value })} />
                        </div>
                    </div>
                    <Button onClick={() => void run(createParkingLotApiV1PbxParkingLotsPost({ body: lotForm }), "Parking créé")}>
                        <Plus /> Créer
                    </Button>
                </div>
            </PageSection>

            <PageSection title="Interphone et annonces" description="*11 suivi du numéro fait décrocher tout seuls les postes choisis. Un seul poste et l'audio dans les deux sens : un interphone ; plusieurs postes : une annonce.">
                <ul className="mb-4 space-y-2">
                    {pagings.map((p) => (
                        <li key={p.id} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 p-3 text-sm" data-testid="paging">
                            <span>
                                <Megaphone className="mr-2 inline size-4" />
                                <strong>{p.name}</strong> <Badge variant="outline">{p.kind === "intercom" ? "Interphone" : "Annonce"}</Badge> · composer{" "}
                                <span className="font-mono">{p.dial}</span> · reçoivent : {names(p.members)}
                                {p.callers.length > 0 && <span className="text-muted-foreground"> · réservé à : {names(p.callers)}</span>}
                            </span>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Supprimer ${p.name}`}
                                onClick={() => window.confirm(`Supprimer « ${p.name} » ?`) && void run(deletePagingApiV1PbxPagingsPagingIdDelete({ path: { paging_id: p.id } }), "Supprimé")}
                            >
                                <Trash2 />
                            </Button>
                        </li>
                    ))}
                </ul>
                <div className="space-y-3 rounded-lg bg-muted/30 p-3">
                    <div className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
                        <div className="space-y-1">
                            <Label htmlFor="paging-name">Nom</Label>
                            <Input id="paging-name" placeholder="ex. Bureau du directeur" value={pagingForm.name} onChange={(e) => setPagingForm({ ...pagingForm, name: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="paging-number">Numéro (après *11)</Label>
                            <Input id="paging-number" inputMode="numeric" value={pagingForm.number} onChange={(e) => setPagingForm({ ...pagingForm, number: e.target.value })} />
                        </div>
                        <div className="flex items-center gap-2 pb-2">
                            <Switch id="paging-duplex" checked={pagingForm.duplex} onCheckedChange={(duplex) => setPagingForm({ ...pagingForm, duplex })} />
                            <Label htmlFor="paging-duplex">Dans les deux sens</Label>
                        </div>
                    </div>
                    <Members users={users} label="Postes qui reçoivent" value={pagingForm.members} onChange={(members) => setPagingForm({ ...pagingForm, members })} />
                    <Members users={users} label="Réservé à (vide : tout le monde)" value={pagingForm.callers} onChange={(callers) => setPagingForm({ ...pagingForm, callers })} />
                    <Button
                        disabled={!pagingForm.name.trim() || !pagingForm.number || !pagingForm.members.length}
                        onClick={async () => {
                            if (await run(createPagingApiV1PbxPagingsPost({ body: pagingForm }), "Interphone créé")) setPagingForm({ name: "", number: "", members: [], callers: [], duplex: true });
                        }}
                    >
                        <Plus /> Créer
                    </Button>
                </div>
            </PageSection>
        </div>
    );
}

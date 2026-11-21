"use client";

import { Crown, KeyRound, Mic, MicOff, Plus, Presentation,RefreshCw, Trash2, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
    conferenceParticipantActionApiV1PbxConferencesConferenceIdParticipantsParticipantIdActionPost,
    createConferenceApiV1PbxConferencesPost,
    deleteConferenceApiV1PbxConferencesConferenceIdDelete,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";

import { elapsed } from "./types";

export type Participant = { id: string; name: string; number: string | null; muted: boolean; admin: boolean; joined_at: string | null };
export type PbxConference = {
    id: number;
    name: string;
    extensions: string[];
    has_pin: boolean;
    has_admin_pin: boolean;
    max_users: number;
    record: boolean;
    participants: Participant[];
};

const EMPTY = { name: "", extension: "", pin: "", admin_pin: "", max_users: 0, record: false, announce_join_leave: true, announce_user_count: true };

export function ConferencesTab({
    conferences,
    liveError,
    onChanged,
    now = Date.now(),
}: {
    conferences: PbxConference[];
    liveError?: string | null;
    onChanged: () => void;
    now?: number;
}) {
    const [form, setForm] = useState<typeof EMPTY | null>(null);

    const act = async (room: PbxConference, participant: Participant, action: "mute" | "unmute" | "kick") => {
        if (action === "kick" && !window.confirm(`Faire sortir ${participant.name} de « ${room.name} » ?`)) return;
        const response = await conferenceParticipantActionApiV1PbxConferencesConferenceIdParticipantsParticipantIdActionPost({
            path: { conference_id: room.id, participant_id: participant.id, action },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Action impossible"));
            return;
        }
        onChanged();
    };
    const pinIssue =
        form &&
        ((form.pin && !/^\d{4,12}$/.test(form.pin)) || (form.admin_pin && !/^\d{4,12}$/.test(form.admin_pin))
            ? "Codes : 4 à 12 chiffres"
            : form.pin && form.pin === form.admin_pin
              ? "Le code organisateur doit différer"
              : null);

    return (
        <PageSection
            title="Salles de conférence"
            description="Des réunions téléphoniques avec code d'accès, et en direct : qui est là, depuis quand, micro coupé ou non."
            actions={
                <>
                    <Button variant="outline" onClick={onChanged}>
                        <RefreshCw /> Actualiser
                    </Button>
                    <Button onClick={() => setForm(EMPTY)}>
                        <Plus /> Nouvelle salle
                    </Button>
                </>
            }
        >
            {liveError && <p className="mb-3 text-sm text-amber-300">Participants indisponibles : {liveError}</p>}
            {conferences.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Aucune salle de conférence.</p>
            ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                    {conferences.map((room) => (
                        <div key={room.id} className="card-weave flex min-w-0 flex-col gap-3 rounded-xl border border-border/60 p-4" data-testid="pbx-conference">
                            <div className="flex items-start gap-2">
                                <Presentation className="mt-0.5 size-5 text-brand-cyan" />
                                <div className="min-w-0 flex-1">
                                    <p className="font-medium">
                                        {room.name} {room.extensions[0] && <span className="font-mono text-sm text-muted-foreground">· {room.extensions[0]}</span>}
                                    </p>
                                    <p className="flex flex-wrap gap-1 pt-1">
                                        {room.has_pin && (
                                            <Badge variant="outline" className="gap-1">
                                                <KeyRound className="size-3" /> Code d&apos;accès
                                            </Badge>
                                        )}
                                        {room.has_admin_pin && (
                                            <Badge variant="outline" className="gap-1">
                                                <Crown className="size-3" /> Code organisateur
                                            </Badge>
                                        )}
                                        {room.max_users > 0 && <Badge variant="outline">{room.max_users} places</Badge>}
                                        {room.record && <Badge variant="outline">Enregistrée</Badge>}
                                    </p>
                                </div>
                                <Badge variant="outline" className={room.participants.length ? "border-emerald-500/50 text-emerald-300" : ""}>
                                    {room.participants.length ? `${room.participants.length} en ligne` : "Vide"}
                                </Badge>
                            </div>
                            {room.participants.length > 0 && (
                                <ul className="space-y-1" data-testid="conference-participants">
                                    {room.participants.map((p) => (
                                        <li key={p.id} className="flex min-w-0 items-center gap-2 rounded-md bg-muted/30 px-2 py-1 text-sm">
                                            {p.admin && <Crown className="size-3.5 shrink-0 text-amber-300" />}
                                            <span className="truncate">{p.name}</span>
                                            {p.number && p.number !== p.name && <span className="font-mono text-xs text-muted-foreground">{p.number}</span>}
                                            <span className="ml-auto shrink-0 text-xs text-muted-foreground">{elapsed(p.joined_at, now)}</span>
                                            <Button
                                                size="icon"
                                                variant="ghost"
                                                aria-label={p.muted ? `Rendre la parole à ${p.name}` : `Couper le micro de ${p.name}`}
                                                onClick={() => void act(room, p, p.muted ? "unmute" : "mute")}
                                            >
                                                {p.muted ? <MicOff className="text-red-300" /> : <Mic />}
                                            </Button>
                                            <Button size="icon" variant="ghost" aria-label={`Faire sortir ${p.name}`} onClick={() => void act(room, p, "kick")}>
                                                <UserX />
                                            </Button>
                                        </li>
                                    ))}
                                </ul>
                            )}
                            <div className="mt-auto flex justify-end border-t border-border/40 pt-2">
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="text-destructive"
                                    aria-label={`Supprimer ${room.name}`}
                                    onClick={async () => {
                                        if (!window.confirm(`Supprimer la salle « ${room.name} » ?`)) return;
                                        const response = await deleteConferenceApiV1PbxConferencesConferenceIdDelete({ path: { conference_id: room.id } });
                                        if (response.error) {
                                            toast.error(detailFromError(response.error, "Suppression impossible"));
                                            return;
                                        }
                                        toast.success("Salle supprimée");
                                        onChanged();
                                    }}
                                >
                                    <Trash2 /> Supprimer
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Dialog open={form !== null} onOpenChange={(open) => !open && setForm(null)}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>Nouvelle salle de conférence</DialogTitle>
                        <DialogDescription>On y entre en composant son numéro, ou par un numéro public qui y mène (onglet Numéros).</DialogDescription>
                    </DialogHeader>
                    {form && (
                        <div className="grid gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                                <Label htmlFor="conf-name">Nom</Label>
                                <Input id="conf-name" placeholder="Point hebdo" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="conf-ext">Numéro</Label>
                                <Input id="conf-ext" placeholder="5001" value={form.extension} onChange={(e) => setForm({ ...form, extension: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="conf-pin">Code participants</Label>
                                <Input id="conf-pin" inputMode="numeric" autoComplete="off" placeholder="facultatif" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="conf-admin">Code organisateur</Label>
                                <Input id="conf-admin" inputMode="numeric" autoComplete="off" placeholder="facultatif" value={form.admin_pin} onChange={(e) => setForm({ ...form, admin_pin: e.target.value })} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="conf-max">Places (0 = illimité)</Label>
                                <Input id="conf-max" type="number" min={0} max={500} value={form.max_users} onChange={(e) => setForm({ ...form, max_users: Number(e.target.value) })} />
                            </div>
                            <div className="space-y-2 pt-1 text-sm">
                                <label className="flex items-center justify-between gap-2">
                                    Annoncer les arrivées
                                    <Switch aria-label="Annoncer les arrivées" checked={form.announce_join_leave} onCheckedChange={(v) => setForm({ ...form, announce_join_leave: v })} />
                                </label>
                                <label className="flex items-center justify-between gap-2">
                                    Enregistrer la réunion
                                    <Switch aria-label="Enregistrer la réunion" checked={form.record} onCheckedChange={(v) => setForm({ ...form, record: v })} />
                                </label>
                            </div>
                        </div>
                    )}
                    <DialogFooter className="items-center">
                        {pinIssue && <p className="mr-auto text-sm text-amber-400">{pinIssue}</p>}
                        <Button variant="outline" onClick={() => setForm(null)}>
                            Annuler
                        </Button>
                        <Button
                            disabled={!form?.name.trim() || !form?.extension.trim() || Boolean(pinIssue)}
                            onClick={async () => {
                                if (!form) return;
                                const response = await createConferenceApiV1PbxConferencesPost({ body: form });
                                if (response.error) {
                                    toast.error(detailFromError(response.error, "Création impossible"));
                                    return;
                                }
                                toast.success(`Salle « ${form.name} » créée`);
                                setForm(null);
                                onChanged();
                            }}
                        >
                            <Presentation /> Créer la salle
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageSection>
    );
}

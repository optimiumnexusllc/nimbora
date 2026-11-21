"use client";

import { KeyRound, Lock, Plus, ShieldX, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    createRestrictionApiV1PbxRestrictionsPost,
    deleteRestrictionApiV1PbxRestrictionsPermissionIdDelete,
    listRestrictionsApiV1PbxRestrictionsGet,
    setRestrictionUsersApiV1PbxRestrictionsPermissionIdUsersPut,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { detailFromError } from "@/lib/apiError";

import type { PbxUser } from "./types";

export type Restriction = {
    id: number;
    name: string;
    mode: "allow" | "deny";
    patterns: string[];
    enabled: boolean;
    has_pin: boolean;
    users: { uuid: string; name: string }[];
};
type Preset = { id: string; label: string; mode: "allow" | "deny"; patterns: string[] };

function UserPicker({ users, selected, onChange }: { users: PbxUser[]; selected: number[]; onChange: (ids: number[]) => void }) {
    const usable = users.filter((u) => u.id != null);
    if (usable.length === 0) return <p className="text-sm text-muted-foreground">Aucun poste.</p>;
    return (
        <div className="grid max-h-48 gap-1 overflow-auto rounded-md border border-border/60 p-2 sm:grid-cols-2">
            {usable.map((u) => (
                <label key={u.uuid} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40">
                    <Checkbox
                        aria-label={u.name}
                        checked={selected.includes(u.id as number)}
                        onCheckedChange={(v) => onChange(v ? [...selected, u.id as number] : selected.filter((id) => id !== u.id))}
                    />
                    {u.name} {u.extension && <span className="font-mono text-xs text-muted-foreground">{u.extension}</span>}
                </label>
            ))}
        </div>
    );
}

export function RestrictionsSection({ users }: { users: PbxUser[] }) {
    const [restrictions, setRestrictions] = useState<Restriction[] | null>(null);
    const [presets, setPresets] = useState<Preset[]>([]);
    const [creating, setCreating] = useState(false);
    const [members, setMembers] = useState<{ restriction: Restriction; ids: number[] } | null>(null);
    const [form, setForm] = useState({ name: "", mode: "deny" as "allow" | "deny", patterns: "", pin: "", user_ids: [] as number[] });

    const load = useCallback(async () => {
        const response = await listRestrictionsApiV1PbxRestrictionsGet();
        if (response.error || !response.data) {
            setRestrictions([]);
            return;
        }
        const data = response.data as unknown as { restrictions: Restriction[]; presets: Preset[] };
        setRestrictions(data.restrictions);
        setPresets(data.presets);
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    const idOf = (uuid: string) => users.find((u) => u.uuid === uuid)?.id ?? null;
    const patterns = form.patterns.split(/[\s,;]+/).filter(Boolean);

    return (
        <PageSection
            title="Restrictions d'appel"
            description="Ce que chaque poste peut composer : pas d'international à l'accueil, pas de numéros surtaxés pour les stagiaires… Un code peut autoriser une exception."
            actions={
                <Button variant="outline" onClick={() => { setForm({ name: "", mode: "deny", patterns: "", pin: "", user_ids: [] }); setCreating(true); }}>
                    <Plus /> Nouvelle restriction
                </Button>
            }
        >
            {restrictions === null ? null : restrictions.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">Aucune restriction : chaque poste peut appeler partout où les routes sortantes mènent.</p>
            ) : (
                <div className="space-y-2">
                    {restrictions.map((r) => (
                        <div key={r.id} className="flex min-w-0 flex-wrap items-center gap-3 rounded-lg border border-border/60 p-3" data-testid="pbx-restriction">
                            <ShieldX className="size-5 shrink-0 text-red-300" />
                            <div className="min-w-0 flex-1">
                                <p className="font-medium">
                                    {r.name}
                                    {r.has_pin && (
                                        <Badge variant="outline" className="ml-2 gap-1">
                                            <KeyRound className="size-3" /> Code de dérogation
                                        </Badge>
                                    )}
                                </p>
                                <p className="text-sm text-muted-foreground">
                                    {r.mode === "deny" ? "Interdit" : "Seulement"} :{" "}
                                    {r.patterns.map((p) => (
                                        <code key={p} className="mr-1 rounded bg-muted/50 px-1">
                                            {p}
                                        </code>
                                    ))}
                                    · {r.users.length ? r.users.map((u) => u.name).join(", ") : "aucun poste"}
                                </p>
                            </div>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setMembers({ restriction: r, ids: r.users.map((u) => idOf(u.uuid)).filter((x): x is number => x != null) })}
                            >
                                <Users /> Postes
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="text-destructive"
                                aria-label={`Supprimer ${r.name}`}
                                onClick={async () => {
                                    if (!window.confirm(`Supprimer la restriction « ${r.name} » ?`)) return;
                                    const response = await deleteRestrictionApiV1PbxRestrictionsPermissionIdDelete({ path: { permission_id: r.id } });
                                    if (response.error) {
                                        toast.error(detailFromError(response.error, "Suppression impossible"));
                                        return;
                                    }
                                    toast.success("Restriction supprimée");
                                    void load();
                                }}
                            >
                                <Trash2 />
                            </Button>
                        </div>
                    ))}
                </div>
            )}

            <Dialog open={creating} onOpenChange={setCreating}>
                <DialogContent className="sm:max-w-xl">
                    <DialogHeader>
                        <DialogTitle>Nouvelle restriction</DialogTitle>
                        <DialogDescription>Les postes choisis ne peuvent plus composer ces numéros (ou seulement ceux-là).</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="flex flex-wrap gap-2">
                            {presets.map((p) => (
                                <Button
                                    key={p.id}
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setForm({ ...form, name: form.name || p.label, mode: p.mode, patterns: p.patterns.join(" ") })}
                                >
                                    {p.label}
                                </Button>
                            ))}
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="restriction-name">Nom</Label>
                            <Input id="restriction-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                        </div>
                        <RadioGroup value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v as "allow" | "deny" })} className="flex gap-4">
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="deny" aria-label="Interdire ces numéros" /> Interdire ces numéros
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <RadioGroupItem value="allow" aria-label="Autoriser seulement ces numéros" /> Autoriser seulement ces numéros
                            </label>
                        </RadioGroup>
                        <div className="space-y-1">
                            <Label htmlFor="restriction-patterns">Motifs</Label>
                            <Input
                                id="restriction-patterns"
                                className="font-mono"
                                placeholder="_00.  _08."
                                value={form.patterns}
                                onChange={(e) => setForm({ ...form, patterns: e.target.value })}
                            />
                            <p className="text-xs text-muted-foreground">Séparés par des espaces. « _ » puis X, N, Z, [plage] et « . » pour la suite.</p>
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="restriction-pin" className="flex items-center gap-1.5">
                                <Lock className="size-3.5" /> Code de dérogation (facultatif)
                            </Label>
                            <Input
                                id="restriction-pin"
                                inputMode="numeric"
                                autoComplete="off"
                                value={form.pin}
                                onChange={(e) => setForm({ ...form, pin: e.target.value })}
                            />
                        </div>
                        <div className="space-y-1">
                            <Label>Postes concernés</Label>
                            <UserPicker users={users} selected={form.user_ids} onChange={(ids) => setForm({ ...form, user_ids: ids })} />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreating(false)}>
                            Annuler
                        </Button>
                        <Button
                            disabled={!form.name.trim() || patterns.length === 0}
                            onClick={async () => {
                                const response = await createRestrictionApiV1PbxRestrictionsPost({
                                    body: { name: form.name.trim(), mode: form.mode, patterns, pin: form.pin.trim(), user_ids: form.user_ids },
                                });
                                if (response.error) {
                                    toast.error(detailFromError(response.error, "Création impossible"));
                                    return;
                                }
                                toast.success("Restriction appliquée");
                                setCreating(false);
                                void load();
                            }}
                        >
                            <ShieldX /> Créer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={members !== null} onOpenChange={(open) => !open && setMembers(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Postes : {members?.restriction.name}</DialogTitle>
                        <DialogDescription>Cochez les postes soumis à cette restriction.</DialogDescription>
                    </DialogHeader>
                    {members && <UserPicker users={users} selected={members.ids} onChange={(ids) => setMembers({ ...members, ids })} />}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setMembers(null)}>
                            Annuler
                        </Button>
                        <Button
                            onClick={async () => {
                                if (!members) return;
                                const response = await setRestrictionUsersApiV1PbxRestrictionsPermissionIdUsersPut({
                                    path: { permission_id: members.restriction.id },
                                    body: { user_ids: members.ids },
                                });
                                if (response.error) {
                                    toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                    return;
                                }
                                toast.success("Postes mis à jour");
                                setMembers(null);
                                void load();
                            }}
                        >
                            Enregistrer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </PageSection>
    );
}

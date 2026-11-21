"use client";

import { ArrowDown, ArrowUp, Bot, Plus, Trash2, Users, UsersRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
    createGroupApiV1PbxGroupsPost,
    deleteGroupApiV1PbxGroupsGroupUuidDelete,
    setGroupFallbackApiV1PbxGroupsGroupUuidFallbackPut,
    setGroupMembersApiV1PbxGroupsGroupUuidMembersPut,
} from "@/client/sdk.gen";
import type { MenuAction } from "@/client/types.gen";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";

import { describeDestination, type Destination, DestinationPicker,type DestinationSources } from "./DestinationPicker";
import type { PbxUser } from "./types";

export type PbxGroup = {
    id: number;
    uuid: string;
    label: string;
    extensions: string[];
    strategy: string;
    ring_seconds: number | null;
    members: { uuid: string; name: string }[];
    fallback: (Destination & { workflow_name?: string | null }) | null;
};

/** Pick members and order them (the order matters when ringing in turn). */
export function OrderedUserPicker({ users, selected, onChange }: { users: PbxUser[]; selected: string[]; onChange: (uuids: string[]) => void }) {
    const name = (uuid: string) => users.find((u) => u.uuid === uuid)?.name ?? uuid;
    const move = (index: number, delta: number) => {
        const next = [...selected];
        const [item] = next.splice(index, 1);
        next.splice(index + delta, 0, item);
        onChange(next);
    };
    return (
        <div className="space-y-2">
            <div className="grid max-h-40 gap-1 overflow-auto rounded-md border border-border/60 p-2 sm:grid-cols-2">
                {users.map((u) => (
                    <label key={u.uuid} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40">
                        <Checkbox
                            aria-label={u.name}
                            checked={selected.includes(u.uuid)}
                            onCheckedChange={(v) => onChange(v ? [...selected, u.uuid] : selected.filter((x) => x !== u.uuid))}
                        />
                        {u.name} {u.extension && <span className="font-mono text-xs text-muted-foreground">{u.extension}</span>}
                    </label>
                ))}
            </div>
            {selected.length > 1 && (
                <ol className="space-y-1 rounded-md border border-border/60 p-2 text-sm" data-testid="group-order">
                    {selected.map((uuid, index) => (
                        <li key={uuid} className="flex items-center gap-2">
                            <Badge variant="outline">{index + 1}</Badge> {name(uuid)}
                            <span className="ml-auto flex">
                                <Button size="icon" variant="ghost" aria-label={`Monter ${name(uuid)}`} disabled={index === 0} onClick={() => move(index, -1)}>
                                    <ArrowUp />
                                </Button>
                                <Button size="icon" variant="ghost" aria-label={`Descendre ${name(uuid)}`} disabled={index === selected.length - 1} onClick={() => move(index, 1)}>
                                    <ArrowDown />
                                </Button>
                            </span>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}

type Form = { label: string; extension: string; strategy: string; ring_seconds: number; user_uuids: string[]; withFallback: boolean; fallback: Destination };

export function GroupsTab({
    groups,
    strategies,
    users,
    sources,
    error,
    onChanged,
}: {
    groups: PbxGroup[];
    strategies: Record<string, string>;
    users: PbxUser[];
    sources: DestinationSources;
    error?: string | null;
    onChanged: () => void;
}) {
    const defaultFallback: Destination = sources.aiEnabled && sources.workflows[0] ? { type: "ai", target_id: sources.workflows[0].id } : { type: "voicemail", target_id: sources.voicemails[0]?.id ?? null };
    const [form, setForm] = useState<Form | null>(null);
    const [members, setMembers] = useState<{ group: PbxGroup; uuids: string[] } | null>(null);
    const [fallback, setFallback] = useState<{ group: PbxGroup; enabled: boolean; value: Destination } | null>(null);

    const run = async (action: () => Promise<{ error?: unknown }>, success: string) => {
        const response = await action();
        if (response.error) {
            toast.error(detailFromError(response.error, "Action impossible"));
            return false;
        }
        toast.success(success);
        onChanged();
        return true;
    };

    return (
        <PageSection
            title="Groupes d'appel"
            description="Un numéro qui fait sonner plusieurs postes — tous ensemble ou chacun son tour — et, si personne ne décroche, un agent IA ou une messagerie."
            actions={
                <Button
                    onClick={() =>
                        setForm({ label: "", extension: "", strategy: "all", ring_seconds: 20, user_uuids: [], withFallback: true, fallback: defaultFallback })
                    }
                >
                    <Plus /> Nouveau groupe
                </Button>
            }
        >
            {error && <p className="mb-3 text-sm text-amber-300">{error}</p>}
            {groups.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Aucun groupe d&apos;appel.</p>
            ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                    {groups.map((g) => (
                        <div key={g.uuid} className="card-weave flex min-w-0 flex-col gap-2 rounded-xl border border-border/60 p-4" data-testid="pbx-group">
                            <div className="flex items-start gap-2">
                                <UsersRound className="mt-0.5 size-5 text-brand-violet" />
                                <div className="min-w-0 flex-1">
                                    <p className="font-medium">
                                        {g.label} {g.extensions[0] && <span className="font-mono text-sm text-muted-foreground">· {g.extensions[0]}</span>}
                                    </p>
                                    <p className="text-sm text-muted-foreground">
                                        {strategies[g.strategy] ?? g.strategy}
                                        {g.ring_seconds ? ` · ${g.ring_seconds} s par poste` : ""}
                                    </p>
                                </div>
                            </div>
                            <p className="text-sm">
                                {g.members.length ? g.members.map((m, i) => `${g.strategy === "linear" ? `${i + 1}. ` : ""}${m.name}`).join(g.strategy === "linear" ? " → " : ", ") : <span className="text-muted-foreground">Aucun membre</span>}
                            </p>
                            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                                Sans réponse :
                                {g.fallback ? (
                                    <span className="flex items-center gap-1 text-foreground">
                                        {g.fallback.type === "ai" && <Bot className="size-4 text-brand-cyan" />}
                                        {g.fallback.type === "ai" ? `Agent IA « ${g.fallback.workflow_name ?? g.fallback.target_id} »` : describeDestination(g.fallback, sources)}
                                    </span>
                                ) : (
                                    " l'appel s'arrête"
                                )}
                            </p>
                            <div className="mt-auto flex flex-wrap justify-end gap-1 border-t border-border/40 pt-2">
                                <Button variant="ghost" size="sm" onClick={() => setMembers({ group: g, uuids: g.members.map((m) => m.uuid) })}>
                                    <Users /> Membres
                                </Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                        setFallback({
                                            group: g,
                                            enabled: Boolean(g.fallback),
                                            value: g.fallback ? { type: g.fallback.type, target_id: g.fallback.target_id } : defaultFallback,
                                        })
                                    }
                                >
                                    <Bot /> Sans réponse
                                </Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="text-destructive"
                                    aria-label={`Supprimer ${g.label}`}
                                    onClick={() => {
                                        if (window.confirm(`Supprimer le groupe « ${g.label} » ?`))
                                            void run(() => deleteGroupApiV1PbxGroupsGroupUuidDelete({ path: { group_uuid: g.uuid } }), "Groupe supprimé");
                                    }}
                                >
                                    <Trash2 />
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Dialog open={form !== null} onOpenChange={(open) => !open && setForm(null)}>
                <DialogContent className="sm:max-w-xl">
                    <DialogHeader>
                        <DialogTitle>Nouveau groupe d&apos;appel</DialogTitle>
                        <DialogDescription>Les postes du groupe sonnent quand on compose son numéro, ou quand un numéro, un menu ou une file y mène.</DialogDescription>
                    </DialogHeader>
                    {form && (
                        <div className="space-y-3">
                            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px]">
                                <div className="space-y-1">
                                    <Label htmlFor="group-label">Nom</Label>
                                    <Input id="group-label" placeholder="Accueil" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="group-ext">Numéro</Label>
                                    <Input id="group-ext" placeholder="4001" value={form.extension} onChange={(e) => setForm({ ...form, extension: e.target.value })} />
                                </div>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px]">
                                <div className="space-y-1">
                                    <Label>Façon de sonner</Label>
                                    <Select value={form.strategy} onValueChange={(strategy) => setForm({ ...form, strategy })}>
                                        <SelectTrigger aria-label="Façon de sonner" className="w-full">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {Object.entries(strategies).map(([id, label]) => (
                                                <SelectItem key={id} value={id}>
                                                    {label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="group-ring">Sonnerie (s)</Label>
                                    <Input id="group-ring" type="number" min={5} max={120} value={form.ring_seconds} onChange={(e) => setForm({ ...form, ring_seconds: Number(e.target.value) })} />
                                </div>
                            </div>
                            <div className="space-y-1">
                                <Label>Membres{form.strategy === "linear" ? " (dans l'ordre)" : ""}</Label>
                                <OrderedUserPicker users={users} selected={form.user_uuids} onChange={(user_uuids) => setForm({ ...form, user_uuids })} />
                            </div>
                            <div className="space-y-2 rounded-lg border border-border/60 p-3">
                                <label className="flex items-center justify-between gap-3 text-sm">
                                    <span className="flex items-center gap-1.5 font-medium">
                                        <Bot className="size-4 text-brand-cyan" /> Si personne ne décroche
                                    </span>
                                    <Switch aria-label="Destination sans réponse" checked={form.withFallback} onCheckedChange={(withFallback) => setForm({ ...form, withFallback })} />
                                </label>
                                {form.withFallback && (
                                    <DestinationPicker label="Destination du groupe sans réponse" value={form.fallback} sources={sources} onChange={(fallback) => setForm({ ...form, fallback })} />
                                )}
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setForm(null)}>
                            Annuler
                        </Button>
                        <Button
                            disabled={!form?.label.trim() || !form?.extension.trim()}
                            onClick={async () => {
                                if (!form) return;
                                const done = await run(
                                    () =>
                                        createGroupApiV1PbxGroupsPost({
                                            body: {
                                                label: form.label,
                                                extension: form.extension,
                                                strategy: form.strategy,
                                                ring_seconds: form.ring_seconds,
                                                user_uuids: form.user_uuids,
                                                fallback: form.withFallback ? (form.fallback as MenuAction) : null,
                                            },
                                        }),
                                    `Groupe « ${form.label} » créé`,
                                );
                                if (done) setForm(null);
                            }}
                        >
                            <UsersRound /> Créer le groupe
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={members !== null} onOpenChange={(open) => !open && setMembers(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Membres : {members?.group.label}</DialogTitle>
                        <DialogDescription>Cochez les postes du groupe ; l&apos;ordre compte quand ils sonnent l&apos;un après l&apos;autre.</DialogDescription>
                    </DialogHeader>
                    {members && <OrderedUserPicker users={users} selected={members.uuids} onChange={(uuids) => setMembers({ ...members, uuids })} />}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setMembers(null)}>
                            Annuler
                        </Button>
                        <Button
                            onClick={async () => {
                                if (!members) return;
                                if (
                                    await run(
                                        () =>
                                            setGroupMembersApiV1PbxGroupsGroupUuidMembersPut({
                                                path: { group_uuid: members.group.uuid },
                                                body: { user_uuids: members.uuids },
                                            }),
                                        "Membres mis à jour",
                                    )
                                )
                                    setMembers(null);
                            }}
                        >
                            Enregistrer
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={fallback !== null} onOpenChange={(open) => !open && setFallback(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Sans réponse : {fallback?.group.label}</DialogTitle>
                        <DialogDescription>Quand aucun membre ne décroche à temps.</DialogDescription>
                    </DialogHeader>
                    {fallback && (
                        <div className="space-y-3">
                            <label className="flex items-center justify-between gap-3 text-sm">
                                Rediriger l&apos;appel
                                <Switch aria-label="Rediriger l'appel" checked={fallback.enabled} onCheckedChange={(enabled) => setFallback({ ...fallback, enabled })} />
                            </label>
                            {fallback.enabled && (
                                <DestinationPicker label="Destination sans réponse" value={fallback.value} sources={sources} onChange={(value) => setFallback({ ...fallback, value })} />
                            )}
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setFallback(null)}>
                            Annuler
                        </Button>
                        <Button
                            onClick={async () => {
                                if (!fallback) return;
                                if (
                                    await run(
                                        () =>
                                            setGroupFallbackApiV1PbxGroupsGroupUuidFallbackPut({
                                                path: { group_uuid: fallback.group.uuid },
                                                body: { fallback: fallback.enabled ? (fallback.value as MenuAction) : null },
                                            }),
                                        "Destination enregistrée",
                                    )
                                )
                                    setFallback(null);
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

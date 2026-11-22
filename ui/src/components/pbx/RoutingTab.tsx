"use client";

import { Crown, Languages, Plus, Route, Save, Sparkles, Trash2, UserCheck, Wrench } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    readRoutingApiV1PbxRoutingGet,
    saveRoutingApiV1PbxRoutingPut,
    simulateRoutingApiV1PbxRoutingSimulatePost,
} from "@/client/sdk.gen";
import { Badge, badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import type { PbxQueue, PbxUser } from "./types";

export type RoutingPolicy = {
    enabled: boolean;
    default_destination: string;
    vip_destination: string;
    usual_advisor: boolean;
    usual_advisor_days: number;
    skills: { name: string; destination: string }[];
    languages: Record<string, string>;
    agents: Record<string, { skills: string[]; languages: string[] }>;
    when_unavailable: "queue" | "callback" | "ai";
    callback_delay_minutes: number;
};

type Decision = {
    destination: string | null;
    reason: string;
    explanation: string;
    steps: string[];
    when_unavailable?: RoutingPolicy["when_unavailable"];
};

const UNAVAILABLE_OUTCOME: Record<RoutingPolicy["when_unavailable"], string> = {
    queue: "le client attendrait dans la file",
    callback: "l'agent IA garderait le client et planifierait un rappel",
    ai: "l'agent IA garderait le client",
};

const NONE = "__none__";
const REASONS: Record<string, string> = {
    vip: "Client VIP",
    usual_advisor: "Conseiller habituel",
    skill: "Compétence",
    skill_agent: "Compétence (poste)",
    language: "Langue",
    default: "Par défaut",
    fallback: "Attente en file",
    unavailable: "Personne de libre",
};

function DestinationSelect({
    value,
    onChange,
    queues,
    users,
    label,
    allowNone = true,
}: {
    value: string;
    onChange: (value: string) => void;
    queues: PbxQueue[];
    users: PbxUser[];
    label: string;
    allowNone?: boolean;
}) {
    return (
        <Select value={value || NONE} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
            <SelectTrigger aria-label={label} className="w-full min-w-0">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {allowNone && <SelectItem value={NONE}>— Aucune —</SelectItem>}
                {queues.map((q) => (
                    <SelectItem key={`q${q.id}`} value={`pbx-queue:${q.id}`}>
                        File {q.name}
                    </SelectItem>
                ))}
                {users
                    .filter((u) => u.extension)
                    .map((u) => (
                        <SelectItem key={`e${u.extension}`} value={`pbx-extension:${u.extension}`}>
                            Poste {u.extension} · {u.name}
                        </SelectItem>
                    ))}
            </SelectContent>
        </Select>
    );
}

export function destinationLabel(destination: string | null, queues: PbxQueue[], users: PbxUser[]): string {
    if (!destination) return "—";
    if (destination.startsWith("pbx-queue:")) {
        const queue = queues.find((q) => String(q.id) === destination.split(":")[1]);
        return queue ? `File ${queue.name}` : destination;
    }
    if (destination.startsWith("pbx-extension:")) {
        const extension = destination.split(":")[1];
        const user = users.find((u) => u.extension === extension);
        return user ? `Poste ${extension} · ${user.name}` : `Poste ${extension}`;
    }
    return destination;
}

/** Intelligent routing of AI hand-offs: policy and simulator. */
export function RoutingTab({ queues, users }: { queues: PbxQueue[]; users: PbxUser[] }) {
    const { user, loading } = useAuth();
    const [policy, setPolicy] = useState<RoutingPolicy | null>(null);
    const [saving, setSaving] = useState(false);
    const [simulation, setSimulation] = useState({ caller_number: "", language: "fr", skill: "" });
    const [decision, setDecision] = useState<Decision | null>(null);
    const fetched = useRef(false);

    const load = useCallback(async () => {
        const response = await readRoutingApiV1PbxRoutingGet();
        if (response.error) {
            toast.error(detailFromError(response.error, "Politique de routage indisponible"));
            return;
        }
        setPolicy(response.data as unknown as RoutingPolicy);
    }, []);

    useEffect(() => {
        if (loading || !user || fetched.current) return;
        fetched.current = true;
        void load();
    }, [loading, user, load]);

    if (!policy) return <p className="py-8 text-center text-sm text-muted-foreground">Chargement…</p>;

    const update = (patch: Partial<RoutingPolicy>) => setPolicy({ ...policy, ...patch });
    const save = async () => {
        setSaving(true);
        const response = await saveRoutingApiV1PbxRoutingPut({ body: policy as never });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        setPolicy(response.data as unknown as RoutingPolicy);
        toast.success("Politique de routage enregistrée");
    };
    const simulate = async () => {
        const response = await simulateRoutingApiV1PbxRoutingSimulatePost({
            body: {
                caller_number: simulation.caller_number || null,
                language: simulation.language || null,
                skill: simulation.skill || null,
            },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Simulation impossible"));
            return;
        }
        setDecision(response.data as unknown as Decision);
    };

    const extensions = users.filter((u) => u.extension);
    const languageRows = Object.entries(policy.languages);

    return (
        <div className="space-y-8" data-testid="routing-tab">
            <div className="rounded-xl border border-border/60 p-4 text-sm text-muted-foreground">
                <p className="mb-2 flex items-center gap-2 font-medium text-foreground">
                    <Route className="size-4" /> Quand un agent IA passe la main (outil de transfert en « Routage intelligent »)
                </p>
                <ol className="list-decimal space-y-1 pl-5">
                    <li>un client VIP va à la destination VIP ;</li>
                    <li>sinon, son conseiller habituel s&apos;il est libre (appris des appels du PBX) ;</li>
                    <li>sinon, la compétence demandée : sa file si quelqu&apos;un y est libre, ou un poste qui l&apos;a (et parle la langue) ;</li>
                    <li>sinon, la file de la langue de l&apos;appel ;</li>
                    <li>sinon, la destination par défaut.</li>
                </ol>
            </div>

            <section className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                    <Label>Destination par défaut</Label>
                    <DestinationSelect label="Destination par défaut" value={policy.default_destination} onChange={(v) => update({ default_destination: v })} queues={queues} users={users} />
                </div>
                <div className="space-y-2">
                    <Label className="flex items-center gap-2">
                        <Crown className="size-4 text-amber-400" /> Clients VIP (étiquette « vip » de la mémoire client)
                    </Label>
                    <DestinationSelect label="Destination VIP" value={policy.vip_destination} onChange={(v) => update({ vip_destination: v })} queues={queues} users={users} />
                </div>
                <div className="flex items-end gap-4">
                    <div className="flex items-center gap-3">
                        <Switch id="usual-advisor" checked={policy.usual_advisor} onCheckedChange={(v) => update({ usual_advisor: v })} />
                        <Label htmlFor="usual-advisor" className="flex items-center gap-2">
                            <UserCheck className="size-4" /> Conseiller habituel en priorité
                        </Label>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="advisor-days" className="text-xs text-muted-foreground">Oublié après (jours)</Label>
                        <Input id="advisor-days" type="number" className="w-24" min={1} max={730} value={policy.usual_advisor_days} onChange={(e) => update({ usual_advisor_days: Number(e.target.value) })} />
                    </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                        <Label>Si personne n&apos;est libre</Label>
                        <Select value={policy.when_unavailable} onValueChange={(v) => update({ when_unavailable: v as RoutingPolicy["when_unavailable"] })}>
                            <SelectTrigger aria-label="Si personne n'est libre">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="queue">Attente dans la file</SelectItem>
                                <SelectItem value="callback">Rappel par un conseiller</SelectItem>
                                <SelectItem value="ai">L&apos;agent IA continue</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    {policy.when_unavailable === "callback" && (
                        <div className="space-y-2">
                            <Label htmlFor="callback-delay">Rappel dans (min)</Label>
                            <Input id="callback-delay" type="number" min={0} max={1440} value={policy.callback_delay_minutes} onChange={(e) => update({ callback_delay_minutes: Number(e.target.value) })} />
                        </div>
                    )}
                </div>
            </section>

            <section className="space-y-3">
                <h3 className="flex items-center gap-2 font-medium">
                    <Wrench className="size-4" /> Compétences
                </h3>
                {policy.skills.map((skill, index) => (
                    <div key={index} className="grid grid-cols-[1fr_1fr_auto] items-center gap-3">
                        <Input
                            aria-label={`Compétence ${index + 1}`}
                            placeholder="ex. Facturation"
                            value={skill.name}
                            onChange={(e) => update({ skills: policy.skills.map((s, i) => (i === index ? { ...s, name: e.target.value } : s)) })}
                        />
                        <DestinationSelect
                            label={`File de la compétence ${index + 1}`}
                            value={skill.destination}
                            onChange={(v) => update({ skills: policy.skills.map((s, i) => (i === index ? { ...s, destination: v } : s)) })}
                            queues={queues}
                            users={users}
                        />
                        <Button variant="ghost" size="icon" aria-label="Retirer la compétence" onClick={() => update({ skills: policy.skills.filter((_, i) => i !== index) })}>
                            <Trash2 />
                        </Button>
                    </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => update({ skills: [...policy.skills, { name: "", destination: "" }] })}>
                    <Plus /> Ajouter une compétence
                </Button>
            </section>

            <section className="space-y-3">
                <h3 className="flex items-center gap-2 font-medium">
                    <Languages className="size-4" /> Langues
                </h3>
                {languageRows.map(([code, destination], index) => (
                    <div key={index} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3">
                        <Input
                            aria-label={`Langue ${index + 1}`}
                            placeholder="en"
                            value={code}
                            onChange={(e) => {
                                const next = languageRows.map(([c, d], i) => (i === index ? [e.target.value, d] : [c, d]));
                                update({ languages: Object.fromEntries(next) });
                            }}
                        />
                        <DestinationSelect
                            label={`File de la langue ${index + 1}`}
                            value={destination}
                            onChange={(v) => update({ languages: { ...policy.languages, [code]: v } })}
                            queues={queues}
                            users={users}
                        />
                        <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Retirer la langue"
                            onClick={() => update({ languages: Object.fromEntries(languageRows.filter((_, i) => i !== index)) })}
                        >
                            <Trash2 />
                        </Button>
                    </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => update({ languages: { ...policy.languages, "": "" } })}>
                    <Plus /> Ajouter une langue
                </Button>
            </section>

            <section className="space-y-3">
                <h3 className="font-medium">Compétences et langues de chaque poste</h3>
                {extensions.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucun poste sur le PBX.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Poste</TableHead>
                                <TableHead>Compétences</TableHead>
                                <TableHead>Langues</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {extensions.map((u) => {
                                const ext = u.extension as string;
                                const info = policy.agents[ext] ?? { skills: [], languages: [] };
                                const setInfo = (patch: Partial<typeof info>) =>
                                    update({ agents: { ...policy.agents, [ext]: { ...info, ...patch } } });
                                return (
                                    <TableRow key={ext}>
                                        <TableCell className="whitespace-nowrap">
                                            {ext} · {u.name}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex flex-wrap gap-1.5">
                                                {policy.skills.filter((s) => s.name.trim()).map((s) => {
                                                    const on = info.skills.includes(s.name);
                                                    return (
                                                        <button
                                                            key={s.name}
                                                            type="button"
                                                            aria-pressed={on}
                                                            className={badgeVariants({ variant: on ? "default" : "outline" })}
                                                            onClick={() =>
                                                                setInfo({
                                                                    skills: on ? info.skills.filter((x) => x !== s.name) : [...info.skills, s.name],
                                                                })
                                                            }
                                                        >
                                                            {s.name}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <Input
                                                aria-label={`Langues du poste ${ext}`}
                                                className="w-36"
                                                placeholder="fr, en"
                                                value={info.languages.join(", ")}
                                                onChange={(e) =>
                                                    setInfo({
                                                        languages: e.target.value
                                                            .split(",")
                                                            .map((x) => x.trim().toLowerCase())
                                                            .filter(Boolean),
                                                    })
                                                }
                                            />
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                )}
            </section>

            <div className="flex justify-end">
                <Button onClick={save} disabled={saving}>
                    <Save /> Enregistrer la politique
                </Button>
            </div>

            <section className="space-y-3 rounded-xl border border-border/60 p-4" data-testid="routing-simulator">
                <h3 className="flex items-center gap-2 font-medium">
                    <Sparkles className="size-4" /> Simulateur : où irait ce client maintenant ?
                </h3>
                <div className="grid gap-3 md:grid-cols-[1fr_8rem_1fr_auto] md:items-end">
                    <div className="space-y-1">
                        <Label htmlFor="sim-phone">Numéro du client</Label>
                        <Input id="sim-phone" placeholder="+225 01 02 03 04 05" value={simulation.caller_number} onChange={(e) => setSimulation({ ...simulation, caller_number: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="sim-language">Langue</Label>
                        <Input id="sim-language" value={simulation.language} onChange={(e) => setSimulation({ ...simulation, language: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="sim-skill">Demande (compétence)</Label>
                        <Input id="sim-skill" placeholder="facturation" value={simulation.skill} onChange={(e) => setSimulation({ ...simulation, skill: e.target.value })} />
                    </div>
                    <Button variant="outline" onClick={simulate}>
                        <Route /> Simuler
                    </Button>
                </div>
                {decision && (
                    <div className="rounded-lg bg-muted/40 p-3 text-sm" data-testid="routing-decision">
                        <div className="flex flex-wrap items-center gap-2 font-medium">
                            <Badge>{REASONS[decision.reason] ?? decision.reason}</Badge>
                            {decision.destination ? destinationLabel(decision.destination, queues, users) : decision.explanation}
                        </div>
                        {decision.reason === "unavailable" && decision.when_unavailable && (
                            <p className="mt-1 text-muted-foreground">
                                → {UNAVAILABLE_OUTCOME[decision.when_unavailable]}
                                {decision.when_unavailable === "callback" && ` (dans ${policy.callback_delay_minutes} min)`}.
                            </p>
                        )}
                        {decision.steps.length > 0 && (
                            <ul className="mt-2 space-y-0.5 text-muted-foreground">
                                {decision.steps.map((step, i) => (
                                    <li key={i}>{step}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                )}
            </section>
        </div>
    );
}

"use client";

import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { type AgentTestInput, lines, parseObject } from "@/lib/agentTests";

type Props = {
    open: boolean;
    initial: AgentTestInput | null;
    title: string;
    saving: boolean;
    onClose: () => void;
    onSave: (test: AgentTestInput) => void;
};

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: React.ReactNode }) {
    return (
        <div className="space-y-1.5">
            <Label htmlFor={id}>{label}</Label>
            {children}
            {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
    );
}

/** Who the customer is, what a good conversation achieves, what is simulated. */
export function TestEditor({ open, initial, title, saving, onClose, onSave }: Props) {
    const [name, setName] = useState("");
    const [persona, setPersona] = useState("");
    const [opening, setOpening] = useState("");
    const [criteria, setCriteria] = useState("");
    const [mustCall, setMustCall] = useState("");
    const [mustNotCall, setMustNotCall] = useState("");
    const [forbidden, setForbidden] = useState("");
    const [mocks, setMocks] = useState("");
    const [context, setContext] = useState("");
    const [maxTurns, setMaxTurns] = useState(8);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!initial) return;
        setName(initial.name);
        setPersona(initial.persona);
        setOpening(initial.opening ?? "");
        setCriteria(initial.success_criteria.join("\n"));
        setMustCall(initial.must_call.join("\n"));
        setMustNotCall(initial.must_not_call.join("\n"));
        setForbidden(initial.forbidden_phrases.join("\n"));
        setMocks(Object.keys(initial.mock_results).length ? JSON.stringify(initial.mock_results, null, 2) : "");
        setContext(Object.keys(initial.initial_context).length ? JSON.stringify(initial.initial_context, null, 2) : "");
        setMaxTurns(initial.max_turns);
        setError(null);
    }, [initial]);

    const submit = () => {
        const mockResults = parseObject(mocks, "Résultats simulés");
        const initialContext = parseObject(context, "Contexte de l'appel");
        const problem = mockResults.error ?? initialContext.error ?? (persona.trim().length < 10 ? "Décrivez le client en quelques phrases" : null) ?? (!name.trim() ? "Donnez un nom au test" : null);
        if (problem) {
            setError(problem);
            return;
        }
        onSave({
            name: name.trim(),
            persona: persona.trim(),
            opening: opening.trim() || null,
            success_criteria: lines(criteria),
            must_call: lines(mustCall),
            must_not_call: lines(mustNotCall),
            forbidden_phrases: lines(forbidden),
            mock_results: mockResults.value ?? {},
            initial_context: initialContext.value ?? {},
            max_turns: maxTurns,
        });
    };

    return (
        <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
            <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
                <SheetHeader>
                    <SheetTitle>{title}</SheetTitle>
                    <SheetDescription>Le client est joué par le modèle de langage de l&apos;entreprise. Aucun outil n&apos;agit réellement pendant un test.</SheetDescription>
                </SheetHeader>
                <div className="space-y-4 px-4 pb-6">
                    <Field id="t-name" label="Nom du test">
                        <Input id="t-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Client pressé, chambre vue mer" />
                    </Field>
                    <Field id="t-persona" label="Le client" hint="À la deuxième personne : qui il est, ce qu'il veut, ce qu'il sait, comment il se comporte.">
                        <Textarea
                            id="t-persona"
                            rows={5}
                            value={persona}
                            maxLength={3000}
                            onChange={(e) => setPersona(e.target.value)}
                            placeholder="Tu es Awa, tu appelles pour une chambre vue mer ce soir, 90 000 F au plus. Tu es pressée et tu raccroches si on te fait attendre."
                        />
                    </Field>
                    <Field id="t-opening" label="Première phrase du client (facultatif)">
                        <Input id="t-opening" value={opening} maxLength={500} onChange={(e) => setOpening(e.target.value)} />
                    </Field>
                    <Field id="t-criteria" label="Critères de réussite" hint="Un par ligne, vérifiables dans la conversation. Jugés par le modèle.">
                        <Textarea id="t-criteria" rows={4} value={criteria} onChange={(e) => setCriteria(e.target.value)} placeholder={"Annonce le prix de la chambre\nPropose de réserver"} />
                    </Field>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <Field id="t-must" label="Outils à utiliser" hint="Nom de fonction, un par ligne.">
                            <Textarea id="t-must" rows={3} value={mustCall} onChange={(e) => setMustCall(e.target.value)} />
                        </Field>
                        <Field id="t-mustnot" label="Outils interdits">
                            <Textarea id="t-mustnot" rows={3} value={mustNotCall} onChange={(e) => setMustNotCall(e.target.value)} />
                        </Field>
                    </div>
                    <Field id="t-forbidden" label="Phrases interdites" hint="L'agent ne doit jamais les dire (une par ligne).">
                        <Textarea id="t-forbidden" rows={2} value={forbidden} onChange={(e) => setForbidden(e.target.value)} />
                    </Field>
                    <Field id="t-mocks" label="Résultats simulés des outils (JSON, facultatif)" hint='Par nom de fonction, ex. { "prendre_rdv": { "status": "booked", "date": "12/12 10:00" } }. Sans cela : un succès neutre ; la recherche dans le catalogue utilise vos vrais articles.'>
                        <Textarea id="t-mocks" rows={4} className="font-mono text-xs" value={mocks} onChange={(e) => setMocks(e.target.value)} />
                    </Field>
                    <Field id="t-context" label="Contexte de l'appel (JSON, facultatif)" hint='Variables des consignes, ex. { "customer_name": "Awa" }.'>
                        <Textarea id="t-context" rows={3} className="font-mono text-xs" value={context} onChange={(e) => setContext(e.target.value)} />
                    </Field>
                    <Field id="t-turns" label="Nombre maximal de répliques du client">
                        <Input id="t-turns" type="number" className="w-24" min={2} max={15} value={maxTurns} onChange={(e) => setMaxTurns(Math.min(15, Math.max(2, Number(e.target.value) || 2)))} />
                    </Field>
                    {error && (
                        <p className="text-sm text-destructive" role="alert">
                            {error}
                        </p>
                    )}
                    <div className="flex justify-end">
                        <Button onClick={submit} disabled={saving}>
                            {saving ? <Loader2 className="animate-spin" /> : <Save />} Enregistrer le test
                        </Button>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}

"use client";

import { Plus, Siren, Trash2 } from "lucide-react";

import type { EmergencyContact, FaqEntry, Offer, Policy } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
    return (
        <Button variant="ghost" size="icon" className="shrink-0 text-muted-foreground" aria-label={label} onClick={onClick}>
            <Trash2 />
        </Button>
    );
}

export function OffersEditor({ offers, onChange }: { offers: Offer[]; onChange: (offers: Offer[]) => void }) {
    const set = (index: number, patch: Partial<Offer>) =>
        onChange(offers.map((o, i) => (i === index ? { ...o, ...patch } : o)));
    return (
        <div className="space-y-3">
            {offers.map((offer, index) => (
                <div key={index} data-testid="offer-row" className="space-y-2 rounded-lg border border-border/60 p-3">
                    <div className="flex gap-2">
                        <Input
                            aria-label="Nom de l'offre"
                            placeholder="Nom (ex. 3 pièces Riviera 3)"
                            value={offer.name}
                            onChange={(e) => set(index, { name: e.target.value })}
                        />
                        <Input
                            aria-label="Prix"
                            placeholder="Prix (ex. 240 000 FCFA / mois)"
                            className="max-w-56"
                            value={offer.price ?? ""}
                            onChange={(e) => set(index, { price: e.target.value })}
                        />
                        <Input
                            aria-label="Catégorie"
                            placeholder="Catégorie"
                            className="max-w-40"
                            value={offer.category ?? ""}
                            onChange={(e) => set(index, { category: e.target.value })}
                        />
                        <RemoveButton label="Retirer l'offre" onClick={() => onChange(offers.filter((_, i) => i !== index))} />
                    </div>
                    <Input
                        aria-label="Description de l'offre"
                        placeholder="Description courte"
                        value={offer.description ?? ""}
                        onChange={(e) => set(index, { description: e.target.value })}
                    />
                </div>
            ))}
            <Button
                variant="outline"
                size="sm"
                disabled={offers.length >= 40}
                onClick={() => onChange([...offers, { name: "", price: "", category: "", description: "" }])}
            >
                <Plus /> Ajouter une offre
            </Button>
            {offers.length >= 40 && (
                <p className="text-xs text-muted-foreground">
                    40 offres au maximum dans la fiche. Pour un catalogue complet, utilisez le catalogue (bientôt).
                </p>
            )}
        </div>
    );
}

export function FaqEditor({ faq, onChange }: { faq: FaqEntry[]; onChange: (faq: FaqEntry[]) => void }) {
    const set = (index: number, patch: Partial<FaqEntry>) =>
        onChange(faq.map((f, i) => (i === index ? { ...f, ...patch } : f)));
    return (
        <div className="space-y-3">
            {faq.map((entry, index) => (
                <div key={index} data-testid="faq-row" className="flex gap-2 rounded-lg border border-border/60 p-3">
                    <div className="flex-1 space-y-2">
                        <Input
                            aria-label="Question"
                            placeholder="Question"
                            value={entry.question}
                            onChange={(e) => set(index, { question: e.target.value })}
                        />
                        <Textarea
                            aria-label="Réponse"
                            placeholder="Réponse que l'agent donnera"
                            rows={2}
                            value={entry.answer}
                            onChange={(e) => set(index, { answer: e.target.value })}
                        />
                    </div>
                    <RemoveButton label="Retirer la question" onClick={() => onChange(faq.filter((_, i) => i !== index))} />
                </div>
            ))}
            <Button
                variant="outline"
                size="sm"
                disabled={faq.length >= 40}
                onClick={() => onChange([...faq, { question: "", answer: "" }])}
            >
                <Plus /> Ajouter une question
            </Button>
        </div>
    );
}

export function PoliciesEditor({
    policies,
    onChange,
}: {
    policies: Policy[];
    onChange: (policies: Policy[]) => void;
}) {
    const set = (index: number, patch: Partial<Policy>) =>
        onChange(policies.map((p, i) => (i === index ? { ...p, ...patch } : p)));
    return (
        <div className="space-y-3">
            {policies.map((policy, index) => (
                <div key={index} className="flex gap-2">
                    <Input
                        aria-label="Titre de la condition"
                        placeholder="Titre (ex. Annulation)"
                        className="max-w-48"
                        value={policy.title}
                        onChange={(e) => set(index, { title: e.target.value })}
                    />
                    <Input
                        aria-label="Contenu de la condition"
                        placeholder="Ce que l'agent doit savoir"
                        value={policy.content}
                        onChange={(e) => set(index, { content: e.target.value })}
                    />
                    <RemoveButton label="Retirer la condition" onClick={() => onChange(policies.filter((_, i) => i !== index))} />
                </div>
            ))}
            <Button
                variant="outline"
                size="sm"
                disabled={policies.length >= 20}
                onClick={() => onChange([...policies, { title: "", content: "" }])}
            >
                <Plus /> Ajouter une condition
            </Button>
        </div>
    );
}

export function EmergencyEditor({
    contacts,
    onChange,
}: {
    contacts: EmergencyContact[];
    onChange: (contacts: EmergencyContact[]) => void;
}) {
    const set = (index: number, patch: Partial<EmergencyContact>) =>
        onChange(contacts.map((c, i) => (i === index ? { ...c, ...patch } : c)));
    return (
        <div className="space-y-2">
            {contacts.map((contact, index) => (
                <div key={index} className="flex gap-2">
                    <Input
                        aria-label="Libellé du numéro d'urgence"
                        placeholder="Ex. Dépannage 24 h/24, SAMU, opposition carte"
                        value={contact.label}
                        onChange={(e) => set(index, { label: e.target.value })}
                    />
                    <Input
                        aria-label="Numéro d'urgence"
                        placeholder="Numéro"
                        className="max-w-48"
                        value={contact.number}
                        onChange={(e) => set(index, { number: e.target.value })}
                    />
                    <RemoveButton
                        label="Retirer le numéro d'urgence"
                        onClick={() => onChange(contacts.filter((_, i) => i !== index))}
                    />
                </div>
            ))}
            <Button
                variant="outline"
                size="sm"
                disabled={contacts.length >= 10}
                onClick={() => onChange([...contacts, { label: "", number: "" }])}
            >
                <Siren /> Ajouter un numéro d&apos;urgence
            </Button>
        </div>
    );
}

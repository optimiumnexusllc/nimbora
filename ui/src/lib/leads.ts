import type { LeadIn } from "@/client/types.gen";

export type Lead = {
    id: number;
    name: string | null;
    phone: string | null;
    email: string | null;
    company: string | null;
    need: string | null;
    budget_min: number | null;
    budget_max: number | null;
    budget_text: string | null;
    currency: string;
    timeline: string | null;
    decision_maker: boolean | null;
    interests: string[];
    stage: Stage;
    stage_label: string;
    score: number;
    source: string;
    owner: string | null;
    notes: string | null;
    lost_reason: string | null;
    next_action: string | null;
    next_action_at: string | null;
    updated_at: string | null;
};
export type Stage = "new" | "qualified" | "proposal" | "negotiation" | "won" | "lost";
export type PipelineStage = { stage: Stage; label: string; count: number; budgets: { currency: string; total: number; text: string }[] };

export const STAGES: { value: Stage; label: string }[] = [
    { value: "new", label: "Nouveau" },
    { value: "qualified", label: "Qualifié" },
    { value: "proposal", label: "Proposition" },
    { value: "negotiation", label: "Négociation" },
    { value: "won", label: "Gagné" },
    { value: "lost", label: "Perdu" },
];

export const SOURCES: Record<string, string> = { call: "Appel", whatsapp: "WhatsApp", web: "Chat web", manual: "Saisie", import: "Import" };

export type LeadForm = {
    name: string;
    phone: string;
    email: string;
    company: string;
    need: string;
    budget_min: string;
    budget_max: string;
    currency: string;
    timeline: string;
    decision_maker: "" | "yes" | "no";
    stage: Stage;
    owner: string;
    next_action: string;
    notes: string;
};

export const EMPTY_LEAD: LeadForm = { name: "", phone: "", email: "", company: "", need: "", budget_min: "", budget_max: "", currency: "XOF", timeline: "", decision_maker: "", stage: "new", owner: "", next_action: "", notes: "" };

export function leadToForm(lead: Lead): LeadForm {
    return {
        name: lead.name ?? "",
        phone: lead.phone ?? "",
        email: lead.email ?? "",
        company: lead.company ?? "",
        need: lead.need ?? "",
        budget_min: lead.budget_min === null ? "" : String(lead.budget_min),
        budget_max: lead.budget_max === null ? "" : String(lead.budget_max),
        currency: lead.currency,
        timeline: lead.timeline ?? "",
        decision_maker: lead.decision_maker === null ? "" : lead.decision_maker ? "yes" : "no",
        stage: lead.stage,
        owner: lead.owner ?? "",
        next_action: lead.next_action ?? "",
        notes: lead.notes ?? "",
    };
}

const amount = (text: string) => {
    const clean = text.replace(/[\s  ]/g, "").replace(",", ".");
    return clean === "" ? null : clean;
};

export function leadFromForm(form: LeadForm, interests: string[] = []): LeadIn {
    const text = (v: string) => v.trim() || null;
    return {
        name: text(form.name),
        phone: text(form.phone),
        email: text(form.email),
        company: text(form.company),
        need: text(form.need),
        budget_min: amount(form.budget_min),
        budget_max: amount(form.budget_max),
        currency: form.currency.trim().toUpperCase() || "XOF",
        timeline: text(form.timeline),
        decision_maker: form.decision_maker === "" ? null : form.decision_maker === "yes",
        interests,
        stage: form.stage,
        owner: text(form.owner),
        next_action: text(form.next_action),
        notes: text(form.notes),
    };
}

/** Hot (≥ 70), warm (≥ 40) or cold. */
export function temperature(score: number): { label: string; className: string } {
    if (score >= 70) return { label: "Chaud", className: "bg-red-500/15 text-red-400 border-red-500/30" };
    if (score >= 40) return { label: "Tiède", className: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
    return { label: "Froid", className: "bg-sky-500/15 text-sky-400 border-sky-500/30" };
}

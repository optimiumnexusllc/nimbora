export type AnswerValue = "yes" | "partial" | "no" | "na";
export type Criterion = { key: string; label: string; description: string; weight: number };
export type QualitySettings = { criteria: Criterion[]; auto_evaluate: boolean; sample_percent: number };
export type AnswerView = { key: string; label: string; answer: AnswerValue | null; comment: string };
export type ReviewStatus = "pending" | "evaluated" | "reviewed" | "failed";
export type ReviewRow = {
    id: number;
    recording_id: number;
    started_at: string | null;
    duration_seconds: number | null;
    direction: string | null;
    customer_phone: string | null;
    agent_extension: string | null;
    agent_name: string | null;
    status: ReviewStatus;
    score: number | null;
    ai_score: number | null;
    ai_summary: string | null;
    ai_error: string | null;
    reviewed_at: string | null;
};
export type Review = ReviewRow & {
    criteria: Criterion[];
    ai_answers: AnswerView[];
    reviewer_answers: AnswerView[] | null;
    reviewer_comment: string | null;
    transcript: string | null;
};
export type Summary = {
    days: number;
    evaluated: number;
    average: number | null;
    to_review: number;
    failed: number;
    agents: { agent_extension: string | null; agent_name: string | null; evaluated: number; average: number | null; reviewed: number }[];
    criteria: { key: string; label: string; answered: number; rate: number | null }[];
};

export const ANSWERS: { value: AnswerValue; label: string }[] = [
    { value: "yes", label: "Oui" },
    { value: "partial", label: "En partie" },
    { value: "no", label: "Non" },
    { value: "na", label: "Sans objet" },
];
export const answerLabel = (a: AnswerValue | null) => ANSWERS.find((x) => x.value === a)?.label ?? "—";

export const STATUS_LABELS: Record<ReviewStatus, string> = {
    pending: "À évaluer",
    evaluated: "À valider",
    reviewed: "Validé",
    failed: "Échec IA",
};

const NUMBER = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
/** « 85 / 100 », or « — » when nothing applied. */
export const scoreText = (score: number | null) => (score === null ? "—" : `${NUMBER.format(score)} / 100`);
export const percentText = (rate: number | null) => (rate === null ? "—" : `${NUMBER.format(rate)} %`);

/** Same weighted share as the API (api/services/quality/service.py score_of). */
export function scoreOf(criteria: Criterion[], answers: Record<string, AnswerValue | undefined>): number | null {
    const value: Record<AnswerValue, number | null> = { yes: 1, partial: 0.5, no: 0, na: null };
    let total = 0;
    let earned = 0;
    for (const c of criteria) {
        const a = answers[c.key];
        const v = a ? value[a] : null;
        if (v === null) continue;
        total += c.weight || 1;
        earned += (c.weight || 1) * v;
    }
    return total ? Math.round((1000 * earned) / total) / 10 : null;
}

export const agentLabel = (r: { agent_name: string | null; agent_extension: string | null }) =>
    [r.agent_name, r.agent_extension].filter(Boolean).join(" · ") || "Conseiller inconnu";

export function durationText(seconds: number | null): string {
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m ? `${m} min ${String(s).padStart(2, "0")}` : `${s} s`;
}

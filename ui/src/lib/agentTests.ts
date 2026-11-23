export type RunStatus = "queued" | "running" | "passed" | "failed" | "error";
export type RunSummary = {
    id: number;
    test_id: number;
    version: "draft" | "published";
    status: RunStatus;
    error: string | null;
    outcome_label: string | null;
    summary: string | null;
    created_at: string | null;
    finished_at: string | null;
};
export type RunResult = {
    outcome: string;
    outcome_label: string;
    transcript: { role: "agent" | "customer"; text: string; node?: string }[];
    tool_calls: { name: string; arguments: Record<string, unknown>; node: string; live?: boolean }[];
    visited_nodes: string[];
    failures: string[];
    checks: { check: string; passed: boolean }[];
    criteria: { criterion: string; passed: boolean; reason: string }[];
    summary: string | null;
    notes: string[];
    metrics: { turns: number; model_calls: number; elapsed_ms: number };
};
export type RunDetail = RunSummary & { result: RunResult | Record<string, never> };
export type AgentTestInput = {
    name: string;
    persona: string;
    opening: string | null;
    success_criteria: string[];
    must_call: string[];
    must_not_call: string[];
    forbidden_phrases: string[];
    mock_results: Record<string, unknown>;
    initial_context: Record<string, unknown>;
    max_turns: number;
};
export type AgentTest = AgentTestInput & { id: number; workflow_id: number; last_run: RunSummary | null };

export const STATUS_LABELS: Record<RunStatus, string> = {
    queued: "En attente",
    running: "En cours",
    passed: "Réussi",
    failed: "Échoué",
    error: "Erreur",
};
export const isPending = (s?: RunStatus | null) => s === "queued" || s === "running";

export const EMPTY_TEST: AgentTestInput = {
    name: "",
    persona: "",
    opening: null,
    success_criteria: [],
    must_call: [],
    must_not_call: [],
    forbidden_phrases: [],
    mock_results: {},
    initial_context: {},
    max_turns: 8,
};

/** One entry per non-empty line. */
export const lines = (text: string) =>
    text
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);

/** A JSON object typed by hand, or an error message in French. */
export function parseObject(text: string, label: string): { value?: Record<string, unknown>; error?: string } {
    if (!text.trim()) return { value: {} };
    try {
        const value = JSON.parse(text);
        if (value && typeof value === "object" && !Array.isArray(value)) return { value };
        return { error: `${label} : un objet JSON est attendu ({ … })` };
    } catch {
        return { error: `${label} : JSON invalide` };
    }
}

export function durationText(ms: number): string {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}

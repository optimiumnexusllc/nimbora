import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { scoreOf } from "@/lib/quality";

import QualityPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    summary: vi.fn(),
    settings: vi.fn(),
    saveSettings: vi.fn(),
    read: vi.fn(),
    submit: vi.fn(),
    evaluate: vi.fn(),
    audio: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    listQualityReviewsApiV1QualityReviewsGet: mocks.list,
    qualitySummaryApiV1QualitySummaryGet: mocks.summary,
    readQualitySettingsApiV1QualitySettingsGet: mocks.settings,
    saveQualitySettingsApiV1QualitySettingsPut: mocks.saveSettings,
    readQualityReviewApiV1QualityReviewsReviewIdGet: mocks.read,
    submitQualityReviewApiV1QualityReviewsReviewIdPut: mocks.submit,
    evaluateRecordingApiV1QualityRecordingsRecordingIdEvaluatePost: mocks.evaluate,
    recordingAudioApiV1PbxRecordingsRecordingIdAudioGet: mocks.audio,
}));

const criteria = [
    { key: "accueil", label: "Accueil", description: "Salue le client", weight: 1 },
    { key: "solution", label: "Réponse apportée", description: "", weight: 3 },
];
const row = {
    id: 7,
    recording_id: 3,
    started_at: "2026-11-21T10:00:00Z",
    duration_seconds: 95,
    direction: "inbound",
    customer_phone: "+2250700112233",
    agent_extension: "1002",
    agent_name: "Awa Koné",
    status: "evaluated",
    score: 62.5,
    ai_score: 62.5,
    ai_summary: "Bon accueil.",
    ai_error: null,
    reviewed_at: null,
};
const review = {
    ...row,
    criteria,
    ai_answers: [
        { key: "accueil", label: "Accueil", answer: "yes", comment: "Se présente" },
        { key: "solution", label: "Réponse apportée", answer: "partial", comment: "Pas de délai donné" },
    ],
    reviewer_answers: null,
    reviewer_comment: null,
    transcript: "Bonjour, Agence Horizon…",
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: { items: [row], total: 1 } });
    mocks.summary.mockResolvedValue({
        data: {
            days: 30,
            evaluated: 1,
            average: 62.5,
            to_review: 1,
            failed: 0,
            agents: [{ agent_extension: "1002", agent_name: "Awa Koné", evaluated: 1, average: 62.5, reviewed: 0 }],
            criteria: [{ key: "accueil", label: "Accueil", answered: 1, rate: 100 }],
        },
    });
    mocks.settings.mockResolvedValue({ data: { criteria, auto_evaluate: false, sample_percent: 100 } });
    mocks.read.mockResolvedValue({ data: review });
    mocks.submit.mockResolvedValue({ data: { ...review, status: "reviewed", score: 100, reviewer_answers: review.ai_answers } });
});

describe("quality helpers", () => {
    it("scores like the API", () => {
        expect(scoreOf(criteria, { accueil: "yes", solution: "partial" })).toBe(62.5);
        expect(scoreOf(criteria, { accueil: "na" })).toBeNull();
    });
});

describe("QualityPage", () => {
    it("lists the calls and lets a supervisor correct the AI", async () => {
        render(<QualityPage />);
        const table = await screen.findByTestId("reviews");
        expect(table.textContent).toContain("Awa Koné · 1002");
        expect(table.textContent).toContain("62,5 / 100");
        expect(screen.getAllByTestId("quality-stat")[2].textContent).toContain("1");

        fireEvent.click(within(table).getByRole("button", { name: "Awa Koné · 1002" }));
        const list = await screen.findByTestId("criteria");
        expect(list.textContent).toContain("Pas de délai donné");
        expect(screen.getByTestId("draft-score").textContent).toBe("62,5 / 100");

        const solution = within(list).getByRole("radiogroup", { name: "Réponse apportée" });
        fireEvent.click(within(solution).getByRole("radio", { name: /Oui/ }));
        expect(screen.getByTestId("draft-score").textContent).toBe("100 / 100");

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Valider l'évaluation/ }));
        });
        expect(mocks.submit).toHaveBeenCalledWith({
            path: { review_id: 7 },
            body: {
                answers: {
                    accueil: { answer: "yes", comment: "" },
                    solution: { answer: "yes", comment: "" },
                },
                comment: "",
            },
        });
        expect(mocks.toast.success).toHaveBeenCalledWith("Évaluation validée");
    });

    it("edits the grid", async () => {
        render(<QualityPage />);
        await screen.findByTestId("reviews");
        const tab = screen.getByRole("tab", { name: "Grille" });
        fireEvent.mouseDown(tab);
        fireEvent.click(tab);
        const grid = await screen.findByTestId("grid");
        fireEvent.click(screen.getByRole("button", { name: /Ajouter un critère/ }));
        expect(within(grid).getAllByLabelText("Critère")).toHaveLength(3);
        mocks.saveSettings.mockResolvedValue({ data: { criteria, auto_evaluate: false, sample_percent: 100 } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer la grille/ }));
        });
        await waitFor(() => expect(mocks.saveSettings).toHaveBeenCalled());
        expect(mocks.saveSettings.mock.calls[0][0].body.criteria[2].label).toBe("Nouveau critère");
    });
});

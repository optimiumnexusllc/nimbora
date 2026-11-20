import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resolveWorkflowConfigurations } from "@/types/workflow-configurations";

import { LanguageDetectionSection, normalizeLanguageDetection } from "./LanguageDetectionSection";

const mocks = vi.hoisted(() => ({
    auth: { loading: false, user: { id: "user" } as { id: string } | null },
    localLanguages: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/UnsavedChangesContext", () => ({ useUnsavedChanges: vi.fn() }));
vi.mock("@/lib/enterpriseApi", () => ({ enterpriseApi: { localLanguages: mocks.localLanguages } }));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.auth = { loading: false, user: { id: "user" } };
    mocks.localLanguages.mockResolvedValue({
        languages: [
            { code: "fr", name: "Français", voices: [{ model: "kokoro", voice: "ff_siwis", label: "Siwis", gender: "female" }] },
            { code: "en", name: "English", voices: [] },
            { code: "sw", name: "Kiswahili", voices: [] },
        ],
    });
});

describe("language detection settings", () => {
    it("normalizes missing settings to a disabled default", () => {
        expect(normalizeLanguageDetection(undefined)).toEqual({
            enabled: false,
            default_language: null,
            languages: [],
            voices: {},
            remember_caller_language: true,
        });
    });

    it("enables detection with allowed languages and a voice, then saves", async () => {
        const save = vi.fn().mockResolvedValue(undefined);
        render(
            <LanguageDetectionSection
                workflowConfigurations={resolveWorkflowConfigurations({ max_call_duration: 600 })}
                onSave={save}
            />,
        );
        const saveButton = screen.getByRole("button", { name: "Save Language Settings" }) as HTMLButtonElement;
        expect(saveButton.disabled).toBe(true);
        fireEvent.click(screen.getByRole("switch", { name: "Detect the caller's language automatically" }));
        await waitFor(() => expect(screen.getByRole("button", { name: "Kiswahili" })).toBeTruthy());
        fireEvent.click(screen.getByRole("button", { name: "English" }));
        fireEvent.click(screen.getByRole("button", { name: "Kiswahili" }));
        const voiceInputs = screen.getAllByPlaceholderText("Automatic (voice id)");
        fireEvent.change(voiceInputs[0], { target: { value: "bm_george" } });
        await act(async () => {
            fireEvent.click(saveButton);
        });
        const saved = save.mock.calls[0][0];
        expect(saved.max_call_duration).toBe(600);
        expect(saved.language_detection).toMatchObject({
            enabled: true,
            languages: ["en", "sw"],
            voices: { en: { voice: "bm_george" } },
            remember_caller_language: true,
        });
    });
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PrivacyPage from "./page";

const mocks = vi.hoisted(() => ({
    read: vi.fn(),
    update: vi.fn(),
    preview: vi.fn(),
    erase: vi.fn(),
    exportData: vi.fn(),
    list: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
    readSettingsApiV1PrivacySettingsGet: mocks.read,
    updateSettingsApiV1PrivacySettingsPut: mocks.update,
    previewRedactionApiV1PrivacyPreviewPost: mocks.preview,
    eraseApiV1PrivacyErasurePost: mocks.erase,
    exportApiV1PrivacyExportPost: mocks.exportData,
    listRequestsApiV1PrivacyRequestsGet: mocks.list,
}));

const SETTINGS = {
    redaction_enabled: false,
    categories: ["card", "cvv", "iban", "ssn", "email", "phone", "ip"],
    mask_in_conversation: false,
    redact_extracted_data: false,
    store_recordings: true,
    recording_retention_days: null,
    transcript_retention_days: null,
    customer_memory_retention_days: null,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: { ...SETTINGS, available_categories: SETTINGS.categories } });
    mocks.update.mockImplementation(async ({ body }) => ({ data: { ...body, available_categories: [] } }));
    mocks.list.mockResolvedValue({
        data: [
            {
                id: 1,
                kind: "erasure",
                subject_hint: "••••••678",
                status: "done",
                counts: { calls: 2, customer_profiles: 1, files: 4 },
                created_at: "2026-11-20T10:00:00Z",
            },
        ],
    });
    mocks.preview.mockResolvedValue({ data: { text: "ma carte [CARD]", counts: { card: 1 } } });
    mocks.erase.mockResolvedValue({ data: { counts: { calls: 1, files: 2, customer_profiles: 1 } } });
});

describe("privacy page", () => {
    it("saves a policy with PCI masking, retention and a narrowed category list", async () => {
        render(<PrivacyPage />);
        await waitFor(() => expect(screen.getByText("••••••678")).toBeTruthy());
        fireEvent.click(screen.getByRole("switch", { name: "Masquer les données personnelles conservées" }));
        fireEvent.click(screen.getByRole("button", { name: /Adresses IP/ }));
        fireEvent.click(screen.getByRole("switch", { name: /Mode PCI/ }));
        fireEvent.change(screen.getByLabelText("Enregistrements audio"), { target: { value: "90" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer la politique/ }));
        });
        const body = mocks.update.mock.calls[0][0].body;
        expect(body).toMatchObject({
            redaction_enabled: true,
            mask_in_conversation: true,
            recording_retention_days: 90,
        });
        expect(body.categories).not.toContain("ip");
        expect(body).not.toHaveProperty("available_categories");
    });

    it("previews masking and asks for confirmation before erasing", async () => {
        render(<PrivacyPage />);
        await waitFor(() => expect(screen.getByRole("button", { name: /Aperçu/ })).toBeTruthy());
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Aperçu/ }));
        });
        expect(screen.getByTestId("redaction-preview").textContent).toBe("ma carte [CARD]");

        fireEvent.change(screen.getByLabelText("Numéro de téléphone"), { target: { value: "+33612345678" } });
        fireEvent.click(screen.getByRole("button", { name: /Effacer ses données/ }));
        expect(mocks.erase).not.toHaveBeenCalled();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Effacer définitivement" }));
        });
        expect(mocks.erase).toHaveBeenCalledWith({ body: { phone: "+33612345678" } });
    });
});

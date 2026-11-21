import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowConfigurations } from "@/types/workflow-configurations";

import { BusinessProfileSection } from "./BusinessProfileSection";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/context/UnsavedChangesContext", () => ({ useUnsavedChanges: vi.fn() }));

describe("BusinessProfileSection", () => {
    it("is on by default and saves the opt-out", async () => {
        const onSave = vi.fn().mockResolvedValue(undefined);
        const config = { max_call_duration: 600 } as unknown as WorkflowConfigurations;
        render(<BusinessProfileSection workflowConfigurations={config} onSave={onSave} />);
        const toggle = screen.getByRole("switch", { name: "Utiliser la fiche entreprise" });
        expect(toggle.getAttribute("aria-checked")).toBe("true");
        expect(screen.getByRole("button", { name: "Enregistrer" })).toHaveProperty("disabled", true);
        fireEvent.click(toggle);
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
        });
        expect(onSave).toHaveBeenCalledWith({ max_call_duration: 600, use_business_profile: false });
        expect(screen.getByRole("link", { name: "Mon entreprise" }).getAttribute("href")).toBe("/business");
    });
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { AlertsBanner } from "./AlertsBanner";
import { AlertsDialog } from "./AlertsDialog";
import type { SupervisionAlert } from "./types";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), test: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    readAlertsApiV1PbxSupervisionAlertsGet: mocks.read,
    saveAlertsApiV1PbxSupervisionAlertsPut: mocks.save,
    testAlertsApiV1PbxSupervisionAlertsTestPost: mocks.test,
}));

const ALERT: SupervisionAlert = {
    key: "long_wait:1",
    kind: "long_wait",
    level: "critical",
    queue_id: 1,
    queue_name: "Ventes",
    value: 250,
    message: "Ventes : un client attend depuis 4 min 10 s (seuil 2 min 00 s)",
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({
        data: {
            settings: {
                enabled: false,
                max_wait_seconds: 120,
                max_waiting: 5,
                no_agent: true,
                queue_ids: [],
                webhook_url: "",
                email_tool_uuid: null,
                email_recipients: [],
                cooldown_minutes: 15,
            },
            email_tools: [{ uuid: "tool-1", name: "E-mail Ivoire Immo" }],
            log: [
                { at: "2026-11-21T10:00:00Z", event: "alert", level: "critical", message: "Ventes : aucun conseiller disponible" },
                { at: "2026-11-21T10:04:00Z", event: "resolved", message: "Ventes : aucun conseiller disponible", duration_seconds: 240 },
            ],
        },
    });
    mocks.save.mockResolvedValue({ data: { settings: {} } });
    mocks.test.mockResolvedValue({ data: { channels: { webhook: "sent", email: "failed: refused" } } });
});

afterEach(() => vi.unstubAllGlobals());

describe("AlertsDialog", () => {
    it("saves rules and channels, then sends a test", async () => {
        render(<AlertsDialog open onOpenChange={vi.fn()} queues={[{ id: 1, name: "Ventes" }, { id: 2, name: "Gestion" }]} />);
        await waitFor(() => expect(screen.getByLabelText("Activer les alertes")).toBeTruthy());
        fireEvent.click(screen.getByRole("switch", { name: "Activer les alertes" }));
        fireEvent.change(screen.getByLabelText("Attente maximale (s)"), { target: { value: "90" } });
        fireEvent.click(screen.getByRole("checkbox", { name: "Surveiller Ventes" }));
        fireEvent.change(screen.getByLabelText(/Webhook/), { target: { value: "https://hooks.slack.com/services/x" } });
        await selectOption(screen.getByLabelText("Outil e-mail"), "E-mail Ivoire Immo");
        fireEvent.change(screen.getByLabelText("Destinataires"), {
            target: { value: "chef@ivoire-immo.ci, superviseur@ivoire-immo.ci\n" },
        });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer et tester/ }));
        });
        expect(mocks.save).toHaveBeenCalledWith({
            body: {
                enabled: true,
                max_wait_seconds: 90,
                max_waiting: 5,
                no_agent: true,
                queue_ids: [1],
                webhook_url: "https://hooks.slack.com/services/x",
                email_tool_uuid: "tool-1",
                email_recipients: ["chef@ivoire-immo.ci", "superviseur@ivoire-immo.ci"],
                cooldown_minutes: 15,
            },
        });
        expect(mocks.test).toHaveBeenCalled();
        expect(mocks.toast.error).toHaveBeenCalledWith("Échec : email (failed: refused)");
    });

    it("shows the log of alerts and their end", async () => {
        render(<AlertsDialog open onOpenChange={vi.fn()} queues={[]} />);
        await waitFor(() => expect(screen.getByRole("tab", { name: /Journal \(2\)/ })).toBeTruthy());
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Journal/ }));
        fireEvent.click(screen.getByRole("tab", { name: /Journal/ }));
        await waitFor(() => expect(screen.getByTestId("alerts-log").textContent).toContain("Rétabli"));
        expect(screen.getByTestId("alerts-log").textContent).toContain("après 4:00");
    });
});

describe("AlertsBanner", () => {
    it("shows alerts and notifies the browser only for new ones", () => {
        const shown: { title: string; body?: string }[] = [];
        class FakeNotification {
            static permission = "granted";
            static requestPermission = vi.fn();
            constructor(title: string, options?: { body?: string }) {
                shown.push({ title, body: options?.body });
            }
        }
        vi.stubGlobal("Notification", FakeNotification);
        const { rerender } = render(<AlertsBanner alerts={[ALERT]} />);
        expect(screen.getByTestId("alerts-banner").textContent).toContain("4 min 10 s");
        expect(shown).toHaveLength(0); // already there when the page opened
        const noAgent = { ...ALERT, key: "no_agent:1", kind: "no_agent" as const, message: "Ventes : aucun conseiller disponible" };
        rerender(<AlertsBanner alerts={[ALERT, noAgent]} />);
        expect(shown).toEqual([{ title: "Supervision · Alerte", body: "Ventes : aucun conseiller disponible" }]);
        rerender(<AlertsBanner alerts={[]} />);
        expect(screen.queryByTestId("alerts-banner")).toBeNull();
    });
});

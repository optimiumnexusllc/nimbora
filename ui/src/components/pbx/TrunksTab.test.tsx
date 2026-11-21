import "@/components/model-connections/test-helpers";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TrunksTab } from "./TrunksTab";
import type { PbxTrunk } from "./types";

const mocks = vi.hoisted(() => ({
    createTrunk: vi.fn(),
    deleteTrunk: vi.fn(),
    createRoute: vi.fn(),
    deleteRoute: vi.fn(),
    test: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    createTrunkApiV1PbxTrunksPost: mocks.createTrunk,
    deleteTrunkApiV1PbxTrunksTrunkIdDelete: mocks.deleteTrunk,
    createOutboundRouteApiV1PbxOutboundRoutesPost: mocks.createRoute,
    deleteOutboundRouteApiV1PbxOutboundRoutesOutcallIdDelete: mocks.deleteRoute,
    testDialApiV1PbxOutboundRoutesTestPost: mocks.test,
}));

const trunk = (id: number, label: string, extra: Partial<PbxTrunk> = {}): PbxTrunk => ({
    id, label, technology: "sip", host: `sip.${label.toLowerCase()}.ci`, username: "u", registration: true,
    registered: true, current_calls: 0, outcalls: [], caller_id_format: "+E164", ...extra,
});
const presets = [{ id: "international", label: "International (00…)", pattern: "_00." }];

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    for (const m of [mocks.createTrunk, mocks.deleteTrunk, mocks.createRoute, mocks.deleteRoute]) m.mockResolvedValue({ data: {} });
});

describe("TrunksTab", () => {
    it("shows registration states and adds a line", async () => {
        const onChanged = vi.fn();
        render(
            <TrunksTab
                trunks={[trunk(1, "Orange"), trunk(2, "MTN", { registered: false }), trunk(3, "SBC", { registration: false, host: null })]}
                routes={[]}
                presets={presets}
                onChanged={onChanged}
            />,
        );
        const rows = screen.getAllByTestId("pbx-trunk");
        expect(rows.map((r) => within(r).getAllByText(/Enregistrée|Non enregistrée|Par adresse IP/)[0].textContent?.trim())).toEqual([
            "Enregistrée",
            "Non enregistrée",
            "Par adresse IP",
        ]);
        fireEvent.click(screen.getByRole("button", { name: /Ajouter une ligne/ }));
        const create = screen.getByRole("button", { name: /Créer la ligne/ });
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Moov" } });
        fireEvent.change(screen.getByLabelText("Serveur de l'opérateur"), { target: { value: "sip.moov.ci" } });
        expect(create).toHaveProperty("disabled", true); // credentials needed to register
        fireEvent.change(screen.getByLabelText("Identifiant SIP"), { target: { value: "2250101" } });
        fireEvent.change(screen.getByLabelText("Mot de passe SIP"), { target: { value: "op-secret" } });
        await act(async () => {
            fireEvent.click(create);
        });
        expect(mocks.createTrunk).toHaveBeenCalledWith({
            body: {
                label: "Moov", host: "sip.moov.ci", port: 5060, transport: "udp", registration: true,
                username: "2250101", password: "op-secret", caller_id_format: "+E164",
            },
        });
        expect(onChanged).toHaveBeenCalled();
    });

    it("builds an outbound route with failover order and a live test", async () => {
        mocks.test.mockResolvedValue({ data: { matched: true, rule_index: 0, sent: "+33612345678", caller_id: null } });
        render(<TrunksTab trunks={[trunk(1, "Orange"), trunk(2, "MTN")]} routes={[]} presets={presets} onChanged={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: /Nouvelle route/ }));
        fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "International" } });
        fireEvent.click(screen.getByRole("checkbox", { name: "MTN" }));
        fireEvent.click(screen.getByRole("button", { name: "Monter MTN" }));
        expect(screen.getByTestId("trunk-order").textContent).toMatch(/1\s*MTN.*2\s*Orange/);
        fireEvent.click(screen.getByRole("button", { name: "_00." }));
        fireEvent.change(screen.getByLabelText("Chiffres retirés 1"), { target: { value: "2" } });
        fireEvent.change(screen.getByLabelText("Préfixe opérateur 1"), { target: { value: "+" } });
        fireEvent.change(screen.getByLabelText("Tester un numéro"), { target: { value: "0033612345678" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Tester" }));
        });
        expect(screen.getByTestId("dial-result").textContent).toBe("Motif _00. → l'opérateur reçoit +33612345678");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Créer la route/ }));
        });
        expect(mocks.createRoute).toHaveBeenCalledWith({
            body: {
                name: "International",
                trunk_ids: [2, 1],
                rules: [{ pattern: "_00.", strip_digits: 2, prefix: "", external_prefix: "+", caller_id: "" }],
                internal_caller_id: false,
            },
        });
    });

    it("lists and deletes routes", async () => {
        const routes = [{
            id: 50, name: "Sortie", enabled: true, internal_caller_id: false, trunks: [{ id: 1, label: "Orange" }, { id: 2, label: "MTN" }],
            rules: [{ pattern: "_0XXXXXXXXX", strip_digits: 0, prefix: "", external_prefix: "", caller_id: "+22527000000" }],
        }];
        render(<TrunksTab trunks={[trunk(1, "Orange")]} routes={routes} presets={presets} onChanged={vi.fn()} />);
        const route = screen.getByTestId("pbx-route");
        expect(route.textContent).toContain("1. Orange  →  2. MTN");
        expect(route.textContent).toContain("+22527000000");
        await act(async () => {
            fireEvent.click(within(route).getByRole("button", { name: "Supprimer Sortie" }));
        });
        expect(mocks.deleteRoute).toHaveBeenCalledWith({ path: { outcall_id: 50 } });
    });
});

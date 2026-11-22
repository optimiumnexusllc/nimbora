import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Call } from "../lib/phone";
import { CallScreen } from "./CallScreen";

afterEach(cleanup);

const customer: Call = { id: "1", direction: "incoming", number: "+2250700112233", name: "Awa Koné", status: "active", startedAt: Date.now(), muted: false, held: false, endReason: null };
const colleague: Call = { id: "2", direction: "outgoing", number: "1002", name: null, status: "active", startedAt: Date.now(), muted: false, held: false, endReason: null };

function handlers() {
    return {
        onAnswer: vi.fn(),
        onDecline: vi.fn(),
        onHangup: vi.fn(),
        onMute: vi.fn(),
        onHold: vi.fn(),
        onDtmf: vi.fn(),
        onTransfer: vi.fn(),
        onConsult: vi.fn(),
        onSwap: vi.fn(),
        onCompleteTransfer: vi.fn(),
        onCancelConsult: vi.fn(),
        onConference: vi.fn(),
    };
}

describe("CallScreen · transfer", () => {
    it("offers to call the colleague first, with the available ones suggested", () => {
        const h = handlers();
        render(
            <CallScreen
                call={customer}
                canTransfer
                colleagues={[
                    { name: "Aya Diallo", extension: "1002", presence: { state: "available", label: "Disponible", status: "" } },
                    { name: "Éric Kouassi", extension: "1003", presence: { state: "on_call", label: "En appel", status: "" } },
                ]}
                {...h}
            />,
        );
        fireEvent.click(screen.getByRole("button", { name: /Transférer/ }));
        const suggested = screen.getByLabelText("Collègues disponibles");
        expect(suggested.textContent).toContain("Aya Diallo");
        expect(suggested.textContent).not.toContain("Éric");
        fireEvent.click(screen.getByRole("button", { name: /Aya Diallo/ }));
        fireEvent.click(screen.getByRole("button", { name: /Appeler d'abord/ }));
        expect(h.onConsult).toHaveBeenCalledWith("1002");
        expect(h.onTransfer).not.toHaveBeenCalled();
    });

    it("still transfers directly when asked", () => {
        const h = handlers();
        render(<CallScreen call={customer} canTransfer {...h} />);
        fireEvent.click(screen.getByRole("button", { name: /Transférer/ }));
        fireEvent.change(screen.getByPlaceholderText("Poste ou numéro"), { target: { value: "1003" } });
        fireEvent.click(screen.getByRole("button", { name: /Transférer directement/ }));
        expect(h.onTransfer).toHaveBeenCalledWith("1003");
    });

    it("during a consultation: swap, transfer, conference, and the red button leaves the colleague", () => {
        const h = handlers();
        render(<CallScreen call={{ ...customer, held: true }} consult={colleague} canTransfer {...h} />);
        expect(screen.getByTestId("call-status").textContent).toContain("En attente");
        expect(screen.getByTestId("consult").textContent).toContain("1002");
        expect((screen.getByRole("button", { name: /Attente|Reprendre/ }) as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(screen.getByRole("button", { name: /Basculer/ }));
        fireEvent.click(screen.getByRole("button", { name: /Conférence/ }));
        fireEvent.click(screen.getByRole("button", { name: "Raccrocher avec le collègue" }));
        expect(h.onSwap).toHaveBeenCalled();
        expect(h.onConference).toHaveBeenCalled();
        expect(h.onCancelConsult).toHaveBeenCalled();
        expect(h.onHangup).not.toHaveBeenCalled();
        const consultGroup = screen.getByRole("group", { name: "Consultation" });
        fireEvent.click(consultGroup.querySelector("button:nth-child(2)") as HTMLButtonElement);
        expect(h.onCompleteTransfer).toHaveBeenCalled();
    });

    it("in a conference: leave them together, or hang up on everyone", () => {
        const h = handlers();
        render(<CallScreen call={customer} consult={colleague} conference notice="Appel transféré" canTransfer {...h} />);
        expect(screen.getByTestId("call-status").textContent).toContain("Conférence à trois");
        expect(screen.queryByRole("button", { name: /Basculer/ })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: /Se retirer/ }));
        expect(h.onCompleteTransfer).toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "Tout raccrocher" }));
        expect(h.onHangup).toHaveBeenCalled();
        expect(screen.getByRole("status").textContent).toBe("Appel transféré");
    });
});

describe("CallScreen · parking", () => {
    it("parks the call in a lot from the transfer panel", () => {
        const h = handlers();
        render(<CallScreen call={customer} canTransfer parking={[{ name: "Accueil", extension: "700" }]} {...h} />);
        fireEvent.click(screen.getByRole("button", { name: /Transférer/ }));
        fireEvent.click(screen.getByRole("button", { name: /Parquer · Accueil/ }));
        expect(h.onTransfer).toHaveBeenCalledWith("700");
    });

    it("says when the call comes from an intercom", () => {
        render(<CallScreen call={{ ...customer, intercom: true }} canTransfer {...handlers()} />);
        expect(screen.getByTestId("call-status").textContent).toContain("Interphone");
    });
});

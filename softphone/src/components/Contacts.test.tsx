import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Directory } from "../lib/api";
import { Contacts } from "./Lists";
import { Settings } from "./Settings";

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const directory: Directory = {
    people: [
        { name: "Koffi Yao", extension: "1001", me: true, presence: { state: "available", label: "Disponible", status: "" } },
        { name: "Aya Diallo", extension: "1002", me: false, presence: { state: "on_call", label: "En appel", status: "" } },
        { name: "Éric Kouassi", extension: "1003", me: false, presence: { state: "away", label: "Absent", status: "En réunion jusqu'à 15 h" } },
        { name: "Moussa Traoré", extension: "1004", me: false, presence: { state: "available", label: "Disponible", status: "" } },
    ],
    services: [],
    customers: [
        { id: 1, name: "Awa Koné", number: "+2250700112233", vip: true, advisor: "Koffi Yao", calls: 4, last_seen_at: null },
        { id: 2, name: null, number: "+2250500998877", vip: false, advisor: null, calls: 1, last_seen_at: null },
    ],
    presence_live: true,
};

describe("Contacts", () => {
    it("shows each colleague's presence and the recent customers", () => {
        render(<Contacts directory={directory} onCall={vi.fn()} />);
        const presence = screen.getAllByTestId("presence").map((p) => p.textContent);
        expect(presence).toEqual(["En appel", "Absent · En réunion jusqu'à 15 h", "Disponible"]);
        expect(screen.getByText("1 disponible")).toBeTruthy();
        const customers = screen.getAllByTestId("customer").map((c) => c.textContent ?? "");
        expect(customers[0]).toContain("Awa Koné");
        expect(customers[0]).toContain("VIP");
        expect(customers[0]).toContain("Conseiller : Koffi Yao");
        expect(customers[1]).toContain("+2250500998877");
    });

    it("searches customers on the server and calls them", async () => {
        vi.useFakeTimers();
        const onCall = vi.fn();
        const search = vi.fn().mockResolvedValue([{ id: 9, name: "Ibrahim Sanogo", number: "+2250101010101", vip: false, advisor: null, calls: 2, last_seen_at: null }]);
        render(<Contacts directory={directory} onCall={onCall} onSearchCustomers={search} />);
        fireEvent.change(screen.getByLabelText("Rechercher un contact"), { target: { value: "sanogo" } });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(350);
        });
        expect(search).toHaveBeenCalledWith("sanogo");
        expect(screen.getByText("Clients")).toBeTruthy();
        fireEvent.click(screen.getByTestId("customer"));
        expect(onCall).toHaveBeenCalledWith("+2250101010101");
        expect(screen.getByText("Personne ne correspond.")).toBeTruthy();
    });

    it("hides customers when the company does not remember them", () => {
        render(<Contacts directory={{ ...directory, customers: null }} onCall={vi.fn()} />);
        expect(screen.queryByText("Clients récents")).toBeNull();
    });
});

describe("Settings · my presence", () => {
    const config = {
        brand: { name: "NIMBORA", pbx_name: "NIMBORA Voice" },
        device: { id: 1, name: "PC", platform: "windows" },
        account: { display_name: "Koffi Yao", extension: "1001", username: "k", password: "p", wss_url: "wss://x", sip_domain: "x" },
        ice_servers: [],
        features: { voicemail_code: "*98", transfer: true, dnd: true },
    } as never;

    it("lets the employee say they are away, with a message", async () => {
        const save = vi.fn().mockResolvedValue(undefined);
        render(
            <Settings
                config={config}
                status={{ dnd: false, forward: { enabled: false, destination: "" } }}
                presence={{ state: "available", label: "Disponible", status: "" }}
                onSaveStatus={vi.fn()}
                onSavePresence={save}
                onOutputDevice={vi.fn()}
                onSignOut={vi.fn()}
            />,
        );
        expect(screen.getByRole("button", { name: "Disponible" }).getAttribute("aria-pressed")).toBe("true");
        fireEvent.change(screen.getByLabelText("Message de présence"), { target: { value: "Déjeuner" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Absent" }));
        });
        expect(save).toHaveBeenCalledWith("away", "Déjeuner");
    });

    it("is hidden when the PBX gives no presence", () => {
        render(
            <Settings
                config={config}
                status={null}
                presence={{ state: "unknown", label: "Inconnu", status: "" }}
                onSaveStatus={vi.fn()}
                onSavePresence={vi.fn()}
                onOutputDevice={vi.fn()}
                onSignOut={vi.fn()}
            />,
        );
        expect(screen.queryByTestId("my-presence")).toBeNull();
    });
});

describe("Recents · parked calls", () => {
    it("lists parked calls and takes one back by dialling its slot", async () => {
        const { Recents } = await import("./Lists");
        const onCall = vi.fn();
        render(
            <Recents
                calls={[]}
                loading={false}
                onCall={onCall}
                onRefresh={vi.fn()}
                parked={[{ lot: "Accueil", slot: "702", number: "+2250700112233", name: "Awa Koné", waiting_seconds: 65, parked_by: null }]}
            />,
        );
        const row = screen.getByTestId("parked");
        expect(row.textContent).toContain("Awa Koné");
        expect(row.textContent).toContain("Place 702");
        fireEvent.click(row);
        expect(onCall).toHaveBeenCalledWith("702");
    });
});

describe("Dialpad · pickup", () => {
    it("intercepts a colleague's ringing call with the pickup code", async () => {
        const { Dialpad } = await import("./Dialpad");
        const onCall = vi.fn();
        render(<Dialpad value="" onChange={vi.fn()} onCall={onCall} disabled={false} pickupCode="*8" />);
        fireEvent.click(screen.getByRole("button", { name: "Intercepter l'appel d'un collègue" }));
        expect(onCall).toHaveBeenCalledWith("*8");
    });
});

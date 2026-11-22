import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamTab } from "./TeamTab";

const mocks = vi.hoisted(() => ({
    pickups: vi.fn(),
    lots: vi.fn(),
    parked: vi.fn(),
    pagings: vi.fn(),
    createPickup: vi.fn(),
    createLot: vi.fn(),
    createPaging: vi.fn(),
    deletePickup: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    listPickupGroupsApiV1PbxPickupGroupsGet: mocks.pickups,
    listParkingLotsApiV1PbxParkingLotsGet: mocks.lots,
    listParkedCallsApiV1PbxParkedCallsGet: mocks.parked,
    listPagingsApiV1PbxPagingsGet: mocks.pagings,
    createPickupGroupApiV1PbxPickupGroupsPost: mocks.createPickup,
    createParkingLotApiV1PbxParkingLotsPost: mocks.createLot,
    createPagingApiV1PbxPagingsPost: mocks.createPaging,
    deletePickupGroupApiV1PbxPickupGroupsGroupIdDelete: mocks.deletePickup,
    deleteParkingLotApiV1PbxParkingLotsLotIdDelete: vi.fn(),
    deletePagingApiV1PbxPagingsPagingIdDelete: vi.fn(),
}));

const users = [
    { uuid: "u-1", name: "Koffi Yao", extension: "1001", email: null, enabled: true },
    { uuid: "u-2", name: "Aya Diallo", extension: "1002", email: null, enabled: true },
] as never;

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.pickups.mockResolvedValue({ data: [{ id: 1, name: "Accueil", code: "*8", members: [{ uuid: "u-1", name: "Koffi Yao", extension: "1001" }, { uuid: "u-2", name: "Aya Diallo", extension: "1002" }] }] });
    mocks.lots.mockResolvedValue({ data: [{ id: 3, name: "Parking accueil", extension: "700", slots_start: "701", slots_end: "720", timeout: 45 }] });
    mocks.parked.mockResolvedValue({ data: [{ lot: "Parking accueil", slot: "702", number: "+2250700112233", name: "Awa Koné", waiting_seconds: 75 }] });
    mocks.pagings.mockResolvedValue({ data: [{ id: 9, name: "Directeur", number: "1", dial: "*111", kind: "intercom", members: [{ uuid: "u-2", name: "Aya Diallo", extension: "1002" }], callers: [] }] });
    for (const create of [mocks.createPickup, mocks.createLot, mocks.createPaging]) create.mockResolvedValue({ data: {} });
});

describe("TeamTab", () => {
    it("shows pickup groups, parking lots with parked calls, and intercoms", async () => {
        render(<TeamTab users={users} />);
        expect((await screen.findByTestId("pickup-group")).textContent).toContain("1001 · Koffi Yao, 1002 · Aya Diallo");
        expect(screen.getByTestId("parking-lot").textContent).toContain("701–720");
        expect(screen.getByTestId("parked-calls").textContent).toContain("Place 702");
        expect(screen.getByTestId("parked-calls").textContent).toContain("Awa Koné · 1 min 15 s");
        expect(screen.getByTestId("paging").textContent).toContain("Interphone");
        expect(screen.getByTestId("paging").textContent).toContain("*111");
    });

    it("creates a pickup group from two extensions", async () => {
        render(<TeamTab users={users} />);
        await screen.findByTestId("pickup-group");
        fireEvent.change(screen.getByLabelText("Nouveau groupe"), { target: { value: "Commerciaux" } });
        const create = screen.getByRole("button", { name: /Créer le groupe/ }) as HTMLButtonElement;
        expect(create.disabled).toBe(true);
        const [koffi, aya] = screen.getAllByLabelText(/1001 · Koffi Yao|1002 · Aya Diallo/).slice(0, 2);
        fireEvent.click(koffi);
        fireEvent.click(aya);
        await act(async () => {
            fireEvent.click(create);
        });
        expect(mocks.createPickup).toHaveBeenCalledWith({ body: { name: "Commerciaux", members: ["u-1", "u-2"] } });
        expect(mocks.toast.success).toHaveBeenCalledWith("Groupe d'interception créé");
    });

    it("creates an intercom to one extension", async () => {
        render(<TeamTab users={users} />);
        await screen.findByTestId("paging");
        fireEvent.change(screen.getByLabelText("Nom", { selector: "#paging-name" }), { target: { value: "Accueil" } });
        fireEvent.change(screen.getByLabelText("Numéro (après *11)"), { target: { value: "2" } });
        const receivers = screen.getByText("Postes qui reçoivent").closest("fieldset") as HTMLElement;
        fireEvent.click(receivers.querySelectorAll("input")[0]);
        await act(async () => {
            fireEvent.click(screen.getAllByRole("button", { name: /^Créer$/ })[1]);
        });
        expect(mocks.createPaging).toHaveBeenCalledWith({ body: { name: "Accueil", number: "2", members: ["u-1"], callers: [], duplex: true } });
    });
});

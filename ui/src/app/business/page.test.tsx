import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BusinessPage from "./page";

const mocks = vi.hoisted(() => ({
    read: vi.fn(),
    update: vi.fn(),
    preview: vi.fn(),
    skills: vi.fn(),
    templates: vi.fn(),
    apply: vi.fn(),
    agent: vi.fn(),
    push: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ loading: false, user: { id: "u" } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    readProfileApiV1BusinessProfileGet: mocks.read,
    updateProfileApiV1BusinessProfilePut: mocks.update,
    previewProfileApiV1BusinessProfilePreviewPost: mocks.preview,
    listSkillsApiV1BusinessSkillsGet: mocks.skills,
    listTemplatesApiV1BusinessTemplatesGet: mocks.templates,
    applyTemplateApiV1BusinessTemplatesTemplateIdApplyPost: mocks.apply,
    createAgentApiV1BusinessTemplatesTemplateIdAgentPost: mocks.agent,
}));

const template = (id: string, label: string, sector = "services", sector_label = "Commerce et services", rules: string[] = []) => ({
    id, label, description: `${label} : description`, icon: "home", activity: "agence immobilière",
    sector, sector_label, rules, recommendations: rules.length ? ["Activez le mode PCI"] : [],
    method: ["Cerner le projet."], collects: ["Budget"], dispositions: ["visite_planifiee"],
    skills: ["book_appointment"], tools: ["book_appointment", "send_message"],
    example_offers: [{ name: "3 pièces" }], example_faq: [], example_policies: [],
});

const stored = {
    enabled: true, industry: "general", name: "Ivoire Immo", timezone: "Africa/Abidjan",
    opening_hours: { mon: [{ open: "08:00", close: "18:00" }] }, closures: [], languages: ["français"],
    offers: [], faq: [], policies: [], skills: { answer_questions: true },
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: stored });
    mocks.update.mockImplementation(async ({ body }) => ({ data: body }));
    mocks.preview.mockResolvedValue({ data: { prompt: "## Votre entreprise : Ivoire Immo", opening_status: "Ouvert en ce moment, jusqu'à 18:00.", characters: 33 } });
    mocks.skills.mockResolvedValue({ data: [{ id: "answer_questions", label: "Répondre aux questions (FAQ)" }, { id: "book_appointment", label: "Prendre rendez-vous" }] });
    mocks.templates.mockResolvedValue({
        data: [
            template("general", "Accueil général"),
            template("real_estate", "Immobilier"),
            template("bank", "Banque", "finance", "Banque, finance et assurance", ["Ne demandez jamais un code PIN."]),
            template("energy", "Énergie : électricité, gaz, solaire", "utilities", "Énergie, eau et service public", ["Danger immédiat d'abord.", "Pas d'intervention."]),
        ],
    });
    mocks.apply.mockResolvedValue({ data: { ...stored, industry: "real_estate", offers: [{ name: "3 pièces" }] } });
    mocks.agent.mockResolvedValue({ data: { workflow_id: 42, name: "Immobilier — Ivoire Immo", missing_tools: ["book_appointment"] } });
});

describe("business page", () => {
    it("edits the card and saves only real content", async () => {
        render(<BusinessPage />);
        const name = await screen.findByLabelText("Nom de l'entreprise");
        expect((name as HTMLInputElement).value).toBe("Ivoire Immo");
        expect(screen.getByRole("button", { name: /Enregistré/ })).toHaveProperty("disabled", true);
        fireEvent.change(screen.getByLabelText("Prénom de l'assistant"), { target: { value: "Sarah" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        const body = mocks.update.mock.calls[0][0].body;
        expect(body.assistant_name).toBe("Sarah");
        expect(body.timezone).toBe("Africa/Abidjan");
        expect(body.opening_hours).toEqual({ mon: [{ open: "08:00", close: "18:00" }] });
        expect(mocks.toast.success).toHaveBeenCalled();
    });

    it("edits hours, offers and FAQ, dropping empty rows", async () => {
        render(<BusinessPage />);
        await screen.findByLabelText("Nom de l'entreprise");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Horaires/ }));
        await waitFor(() => expect(screen.getByLabelText("Mardi ouvert")).toBeTruthy());
        fireEvent.click(screen.getByRole("button", { name: /Appliquer les horaires du lundi/ }));
        fireEvent.click(screen.getByLabelText("Dimanche ouvert"));
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Offres et FAQ/ }));
        await waitFor(() => expect(screen.getByRole("button", { name: /Ajouter une offre/ })).toBeTruthy());
        fireEvent.click(screen.getByRole("button", { name: /Ajouter une offre/ }));
        fireEvent.click(screen.getByRole("button", { name: /Ajouter une offre/ }));
        fireEvent.change(screen.getAllByLabelText("Nom de l'offre")[0], { target: { value: "Studio Marcory" } });
        fireEvent.change(screen.getAllByLabelText("Prix")[0], { target: { value: "90 000 FCFA" } });
        fireEvent.click(screen.getByRole("button", { name: /Ajouter une question/ }));
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        const body = mocks.update.mock.calls[0][0].body;
        expect(Object.keys(body.opening_hours)).toEqual(["mon", "tue", "wed", "thu", "fri", "sun"]);
        expect(body.opening_hours.fri).toEqual([{ open: "08:00", close: "18:00" }]);
        expect(body.offers).toEqual([{ name: "Studio Marcory", price: "90 000 FCFA", category: "", description: "" }]);
        expect(body.faq).toEqual([]);
    });

    it("shows what the agents read", async () => {
        render(<BusinessPage />);
        await screen.findByLabelText("Nom de l'entreprise");
        fireEvent.mouseDown(screen.getByRole("tab", { name: /Ce que lisent les agents/ }));
        await waitFor(() => expect(screen.getByTestId("business-preview").textContent).toContain("Votre entreprise : Ivoire Immo"));
        expect(screen.getByText("Ouvert en ce moment, jusqu'à 18:00.")).toBeTruthy();
    });

    it("applies a trade and creates its agent", async () => {
        render(<BusinessPage />);
        await screen.findByLabelText("Nom de l'entreprise");
        fireEvent.click(screen.getByTestId("template-real_estate"));
        expect(await screen.findByText("Cerner le projet.")).toBeTruthy();
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Choisir ce métier/ }));
        });
        expect(mocks.apply).toHaveBeenCalledWith({ path: { template_id: "real_estate" }, body: { with_examples: true } });
        await waitFor(() => expect(screen.getByTestId("template-real_estate").textContent).toContain("Votre métier"));
        // Once chosen, the trade is shown alone; the full catalogue opens on demand.
        expect(screen.queryByTestId("template-general")).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Voir les 4 métiers" }));
        expect(screen.getByTestId("template-general").textContent).not.toContain("Votre métier");
        fireEvent.click(screen.getByRole("button", { name: "Masquer les autres métiers" }));
        expect(screen.queryByLabelText("Rechercher un métier")).toBeNull();

        fireEvent.click(screen.getByTestId("template-real_estate"));
        await act(async () => {
            fireEvent.click(await screen.findByRole("button", { name: /Créer l'agent immobilier/ }));
        });
        expect(mocks.agent).toHaveBeenCalledWith({ path: { template_id: "real_estate" }, body: {} });
        const [, options] = mocks.toast.success.mock.calls.at(-1)!;
        expect(options.description).toContain("Prise de rendez-vous");
        options.action.onClick();
        expect(mocks.push).toHaveBeenCalledWith("/workflow/42");
    });

    it("asks to save before applying a trade", async () => {
        render(<BusinessPage />);
        fireEvent.change(await screen.findByLabelText("Nom de l'entreprise"), { target: { value: "Autre" } });
        fireEvent.click(screen.getByTestId("template-real_estate"));
        await act(async () => {
            fireEvent.click(await screen.findByRole("button", { name: /Choisir ce métier/ }));
        });
        expect(mocks.apply).not.toHaveBeenCalled();
        expect(mocks.toast.error).toHaveBeenCalledWith("Enregistrez d'abord vos modifications");
    });

    it("reports validation errors from the API", async () => {
        mocks.update.mockResolvedValue({ error: { detail: [{ msg: "L'heure de fermeture doit suivre l'ouverture" }] } });
        render(<BusinessPage />);
        fireEvent.change(await screen.findByLabelText("Activité"), { target: { value: "agence" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        expect(mocks.toast.error.mock.calls[0][0]).toContain("L'heure de fermeture doit suivre l'ouverture");
    });

    it("groups trades by sector, searches them and shows their mandatory rules", async () => {
        render(<BusinessPage />);
        await screen.findByLabelText("Nom de l'entreprise");
        expect(screen.getAllByTestId("sector-group").map((g) => g.querySelector("h3")?.textContent)).toEqual([
            "Commerce et services",
            "Banque, finance et assurance",
            "Énergie, eau et service public",
        ]);
        expect(screen.getByTestId("template-energy").textContent).toContain("2 règles impératives");
        fireEvent.change(screen.getByLabelText("Rechercher un métier"), { target: { value: "energie" } });
        expect(screen.queryByTestId("template-bank")).toBeNull();
        expect(screen.getByTestId("template-energy")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Rechercher un métier"), { target: { value: "finance" } });
        fireEvent.click(screen.getByTestId("template-bank"));
        expect(await screen.findByText("Ne demandez jamais un code PIN.")).toBeTruthy();
        expect(screen.getByText("Activez le mode PCI")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Rechercher un métier"), { target: { value: "zzz" } });
    });

    it("saves emergency numbers and drops incomplete ones", async () => {
        render(<BusinessPage />);
        await screen.findByLabelText("Nom de l'entreprise");
        fireEvent.click(screen.getByRole("button", { name: /Ajouter un numéro d'urgence/ }));
        fireEvent.click(screen.getByRole("button", { name: /Ajouter un numéro d'urgence/ }));
        fireEvent.change(screen.getAllByLabelText("Libellé du numéro d'urgence")[0], { target: { value: "Dépannage 24 h/24" } });
        fireEvent.change(screen.getAllByLabelText("Numéro d'urgence")[0], { target: { value: "+225 27 21 00 00 00" } });
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        expect(mocks.update.mock.calls[0][0].body.emergency_contacts).toEqual([
            { label: "Dépannage 24 h/24", number: "+225 27 21 00 00 00" },
        ]);
    });
});

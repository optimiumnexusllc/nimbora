import type {
    BusinessProfile,
    Closure,
    EmergencyContact,
    FaqEntry,
    Offer,
    Policy,
    Skills,
    TimeRange,
} from "@/client/types.gen";

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];

export const DAY_LABELS: Record<Day, string> = {
    mon: "Lundi",
    tue: "Mardi",
    wed: "Mercredi",
    thu: "Jeudi",
    fri: "Vendredi",
    sat: "Samedi",
    sun: "Dimanche",
};

export const SKILL_DESCRIPTIONS: Record<keyof Skills, string> = {
    answer_questions: "Répond à partir de la fiche et de la FAQ, et dit honnêtement quand il ne sait pas.",
    hours_and_location: "Donne horaires, adresse et itinéraire, en tenant compte de l'ouverture en ce moment.",
    present_offers: "Présente les offres et les prix de la fiche, sans jamais en inventer.",
    take_message: "Prend un message complet (nom, numéro, motif, moment pour rappeler).",
    book_appointment: "Propose et réserve un rendez-vous (avec l'outil de prise de rendez-vous).",
    qualify_leads: "Cerne le besoin, le budget, le délai et les coordonnées d'un prospect.",
    human_handoff: "Propose un conseiller si la personne le demande ou est mécontente.",
    collect_feedback: "Demande en fin d'échange si la personne est satisfaite.",
};

export const TIMEZONES = [
    "Africa/Abidjan",
    "Africa/Dakar",
    "Africa/Bamako",
    "Africa/Niamey",
    "Africa/Lagos",
    "Africa/Douala",
    "Africa/Kinshasa",
    "Africa/Casablanca",
    "Africa/Tunis",
    "Africa/Algiers",
    "Africa/Nairobi",
    "Africa/Johannesburg",
    "Europe/Paris",
    "Europe/Brussels",
    "Europe/Zurich",
    "Europe/London",
    "America/Montreal",
    "America/New_York",
    "Indian/Reunion",
    "UTC",
];

export type Profile = Required<
    Omit<
        BusinessProfile,
        "opening_hours" | "closures" | "offers" | "faq" | "policies" | "skills" | "languages" | "emergency_contacts"
    >
> & {
    emergency_contacts: EmergencyContact[];
    opening_hours: Record<string, TimeRange[]>;
    closures: Closure[];
    languages: string[];
    offers: Offer[];
    faq: FaqEntry[];
    policies: Policy[];
    skills: Required<Skills>;
};

export function browserTimezone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
        return "UTC";
    }
}

export function normalizeProfile(p: BusinessProfile | undefined | null): Profile {
    const skills: Required<Skills> = {
        answer_questions: true,
        hours_and_location: true,
        present_offers: true,
        take_message: true,
        book_appointment: false,
        qualify_leads: false,
        human_handoff: true,
        collect_feedback: false,
        ...(p?.skills ?? {}),
    } as Required<Skills>;
    return {
        enabled: p?.enabled ?? true,
        industry: p?.industry ?? "general",
        name: p?.name ?? "",
        activity: p?.activity ?? "",
        description: p?.description ?? "",
        assistant_name: p?.assistant_name ?? "",
        tone: p?.tone ?? "",
        phone: p?.phone ?? "",
        whatsapp: p?.whatsapp ?? "",
        email: p?.email ?? "",
        website: p?.website ?? "",
        address: p?.address ?? "",
        city: p?.city ?? "",
        country: p?.country ?? "",
        directions: p?.directions ?? "",
        maps_url: p?.maps_url ?? "",
        emergency_contacts: [...(p?.emergency_contacts ?? [])],
        // A card never saved yet starts in the browser's time zone.
        timezone: p?.timezone && (p.timezone !== "UTC" || p.name) ? p.timezone : browserTimezone(),
        opening_hours: { ...(p?.opening_hours ?? {}) },
        closures: [...(p?.closures ?? [])],
        languages: [...(p?.languages ?? [])],
        offers: [...(p?.offers ?? [])],
        faq: [...(p?.faq ?? [])],
        policies: [...(p?.policies ?? [])],
        instructions: p?.instructions ?? "",
        skills,
    };
}

/** What is sent to the API: empty rows (being typed) are dropped. */
export function cleanProfile(p: Profile): Profile {
    const hours: Record<string, TimeRange[]> = {};
    for (const day of DAYS) {
        const ranges = (p.opening_hours[day] ?? []).filter((r) => r.open && r.close);
        if (ranges.length) hours[day] = ranges;
    }
    return {
        ...p,
        opening_hours: hours,
        closures: p.closures.filter((c) => c.date),
        emergency_contacts: p.emergency_contacts.filter((c) => c.label.trim() && c.number.trim()),
        offers: p.offers.filter((o) => o.name.trim()),
        faq: p.faq.filter((f) => f.question.trim() && f.answer.trim()),
        policies: p.policies.filter((x) => x.title.trim() && x.content.trim()),
        languages: p.languages.map((l) => l.trim()).filter(Boolean),
    };
}

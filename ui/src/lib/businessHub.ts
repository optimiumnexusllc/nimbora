export type Kpi = { value: number; previous: number; change: number | null; [extra: string]: number | null };
export type Hub = {
    period: "7d" | "30d" | "90d";
    timezone: string;
    kpis: Record<"conversations" | "ai_calls" | "human_calls" | "appointments" | "leads" | "customers", Kpi>;
    channels: { channel: "phone" | "whatsapp" | "web"; label: string; count: number; previous: number; share: number }[];
    actions: Record<string, number | null>;
    pipeline: { currency: string; open_leads: number; budget: number; text: string }[];
    daily: { day: string; phone_ai: number; phone_human: number; whatsapp: number; web: number; appointments: number; leads: number }[];
};

/** Daily activity series, in fixed categorical order (validated palette, dark and light). */
export const SERIES = [
    { key: "phone_ai", label: "Appels IA", dark: "#3987e5", light: "#2a78d6" },
    { key: "phone_human", label: "Appels humains", dark: "#d95926", light: "#eb6834" },
    { key: "whatsapp", label: "WhatsApp", dark: "#199e70", light: "#1baf7a" },
    { key: "web", label: "Web", dark: "#c98500", light: "#eda100" },
] as const;

const NUMBER = new Intl.NumberFormat("fr-FR");
export const formatNumber = (n: number) => NUMBER.format(n);

/** « +12 % », « −5 % », or « nouveau » when nothing happened before. */
export function changeText(kpi: Kpi): { text: string; tone: "up" | "down" | "flat" } {
    if (kpi.change === null) return { text: kpi.value ? "nouveau" : "—", tone: "flat" };
    if (kpi.change === 0) return { text: "stable", tone: "flat" };
    const sign = kpi.change > 0 ? "+" : "−";
    return { text: `${sign}${NUMBER.format(Math.abs(kpi.change))} %`, tone: kpi.change > 0 ? "up" : "down" };
}

/** « 21 nov. » from « 2026-11-21 ». */
export function shortDay(day: string): string {
    const [y, m, d] = day.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });
}

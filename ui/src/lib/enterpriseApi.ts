/**
 * Typed calls for the enterprise endpoints (subscriptions, operator console,
 * human contact center, local AI). They go through the shared hey-api client,
 * so authentication and the backend base URL work exactly like the generated SDK.
 */
import { client } from "@/client/client.gen";

export type Plan = {
    code: string;
    name: string;
    description: string | null;
    currency: string;
    monthly_price_cents: number;
    included_minutes: number | null;
    overage_price_cents_per_minute: number | null;
    max_concurrent_calls: number | null;
    max_agents: number | null;
    max_human_seats: number | null;
    max_campaigns: number | null;
    features: Record<string, boolean>;
    purchasable: boolean;
    is_public: boolean;
    is_active: boolean;
};

export type Subscription = {
    platform_name: string;
    organization_id: number;
    plan_code: string;
    plan_name: string;
    status: "trialing" | "active" | "past_due" | "suspended" | "canceled";
    period_start: string;
    period_end: string;
    trial_ends_at: string | null;
    used_minutes: number;
    included_minutes: number | null;
    remaining_minutes: number | null;
    overage_minutes: number;
    estimated_overage_cents: number;
    limits: Record<string, number | null>;
    features: Record<string, boolean>;
    usable: boolean;
    blocked_reason: string | null;
    can_manage_billing: boolean;
};

export type Tenant = {
    organization_id: number;
    company_name: string | null;
    billing_email: string | null;
    member_emails: string[];
    plan_code: string;
    status: Subscription["status"];
    current_period_start: string;
    current_period_end: string;
    trial_ends_at: string | null;
    limit_overrides: Record<string, unknown>;
    stripe_customer_id: string | null;
    notes: string | null;
    created_at: string | null;
};

export type TenantUpdate = Partial<{
    plan_code: string;
    status: Subscription["status"];
    trial_ends_at: string | null;
    limit_overrides: Record<string, unknown>;
    company_name: string;
    billing_email: string;
    notes: string;
}>;

export type AgentSummary = { id: number; display_name: string; extension: string };

export type Queue = {
    id: number;
    slug: string;
    name: string;
    transfer_destination: string;
    strategy: string;
    ring_timeout_seconds: number;
    max_wait_seconds: number;
    wrapup_seconds: number;
    announce_position: boolean;
    overflow_destination: string | null;
    is_active: boolean;
    agents: AgentSummary[];
};

export type QueueInput = {
    slug?: string;
    name?: string;
    strategy?: string;
    ring_timeout_seconds?: number;
    max_wait_seconds?: number;
    wrapup_seconds?: number;
    announce_position?: boolean;
    overflow_destination?: string | null;
    is_active?: boolean;
    agent_ids?: number[];
};

export type Agent = {
    id: number;
    display_name: string;
    extension: string;
    sip_username: string;
    user_id: number | null;
    is_active: boolean;
    queues: string[];
};

export type SoftphoneCredentials = {
    agent: Agent;
    sip_username: string;
    sip_password: string;
    sip_realm: string;
    wss_url: string | null;
};

export type Handoff = {
    id: string;
    queue_slug: string | null;
    caller_number: string | null;
    status: "pending" | "answered";
    summary_status: "pending" | "ready" | "failed" | "skipped";
    reason: string | null;
    summary: string | null;
    customer_name: string | null;
    sentiment: "positive" | "neutral" | "frustrated" | "angry" | null;
    next_step: string | null;
    collected_data: Record<string, unknown>;
    transcript: { speaker: "client" | "agent_ia"; text: string }[];
    workflow_run_id: number | null;
    created_at: string | null;
    answered_at: string | null;
};

export type LocalLanguage = {
    code: string;
    name: string;
    stt_language: string;
    voices: { model: string; voice: string; label: string; gender: string }[];
    note: string;
};

export type LocalAIInfo = {
    enabled: boolean;
    default_language: string;
    llm_model: string;
    stt_model: string;
    languages: LocalLanguage[];
    stt_languages: string[];
};

export class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
        super(message);
        this.status = status;
    }
}

type Method = "get" | "post" | "patch" | "put" | "delete";

function errorMessage(error: unknown): string {
    if (error && typeof error === "object" && "detail" in error) {
        const detail = (error as { detail: unknown }).detail;
        if (typeof detail === "string") return detail;
        if (Array.isArray(detail)) {
            return detail
                .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
                .join(", ");
        }
    }
    return "La requête a échoué.";
}

async function call<T>(method: Method, url: string, body?: unknown): Promise<T> {
    const result = await client[method]({
        url,
        ...(body !== undefined ? { body, headers: { "Content-Type": "application/json" } } : {}),
    });
    if (result.error !== undefined || !result.response?.ok) {
        throw new ApiError(result.response?.status ?? 0, errorMessage(result.error));
    }
    return result.data as T;
}

const BASE = "/api/v1";

export const enterpriseApi = {
    // Tenant: subscription
    listPlans: () => call<Plan[]>("get", `${BASE}/saas/plans`),
    getSubscription: () => call<Subscription>("get", `${BASE}/saas/subscription`),
    startCheckout: (plan_code: string) =>
        call<{ url: string }>("post", `${BASE}/saas/checkout`, { plan_code }),
    openBillingPortal: () => call<{ url: string }>("post", `${BASE}/saas/portal`),

    // Operator console
    adminListPlans: () => call<Plan[]>("get", `${BASE}/saas/admin/plans`),
    adminUpsertPlan: (code: string, fields: Partial<Plan> & { unlimited?: string[] }) =>
        call<Plan>("put", `${BASE}/saas/admin/plans/${encodeURIComponent(code)}`, fields),
    adminListTenants: (page = 1, status?: string) =>
        call<{ tenants: Tenant[]; total: number; page: number; limit: number }>(
            "get",
            `${BASE}/saas/admin/tenants?page=${page}&limit=50${status ? `&status=${status}` : ""}`,
        ),
    adminTenantUsage: (organizationId: number) =>
        call<Subscription>("get", `${BASE}/saas/admin/tenants/${organizationId}/usage`),
    adminUpdateTenant: (organizationId: number, update: TenantUpdate) =>
        call<Tenant>("patch", `${BASE}/saas/admin/tenants/${organizationId}`, update),

    // Contact center
    listQueues: () => call<Queue[]>("get", `${BASE}/contact-center/queues`),
    createQueue: (input: QueueInput) => call<Queue>("post", `${BASE}/contact-center/queues`, input),
    updateQueue: (id: number, input: QueueInput) =>
        call<Queue>("patch", `${BASE}/contact-center/queues/${id}`, input),
    deleteQueue: (id: number) => call<void>("delete", `${BASE}/contact-center/queues/${id}`),
    listAgents: () => call<Agent[]>("get", `${BASE}/contact-center/agents`),
    createAgent: (input: { display_name: string; extension: string; user_id?: number | null }) =>
        call<SoftphoneCredentials>("post", `${BASE}/contact-center/agents`, input),
    updateAgent: (id: number, input: Partial<Pick<Agent, "display_name" | "user_id" | "is_active">>) =>
        call<Agent>("patch", `${BASE}/contact-center/agents/${id}`, input),
    resetAgentPassword: (id: number) =>
        call<SoftphoneCredentials>("post", `${BASE}/contact-center/agents/${id}/reset-password`),
    deleteAgent: (id: number) => call<void>("delete", `${BASE}/contact-center/agents/${id}`),
    claimSeat: (id: number) => call<Agent>("post", `${BASE}/contact-center/agents/${id}/claim`),
    getHandoff: (id: string) => call<Handoff>("get", `${BASE}/contact-center/handoffs/${encodeURIComponent(id)}`),
    myPendingHandoffs: () => call<Handoff[]>("get", `${BASE}/contact-center/handoffs?mine=true&status=pending`),
    listHandoffs: () => call<Handoff[]>("get", `${BASE}/contact-center/handoffs`),
    acceptHandoff: (id: string) =>
        call<Handoff>("post", `${BASE}/contact-center/handoffs/${encodeURIComponent(id)}/accept`),
    mySeat: () => call<Agent | null>("get", `${BASE}/contact-center/me`),

    // Local AI
    localLanguages: () => call<LocalAIInfo>("get", `${BASE}/local-ai/languages`),
};

export function formatPrice(cents: number, currency: string): string {
    return new Intl.NumberFormat("fr-FR", { style: "currency", currency: currency.toUpperCase() }).format(
        cents / 100,
    );
}

export function formatLimit(value: number | null | undefined, unit = ""): string {
    if (value === null || value === undefined) return "Illimité";
    return `${value.toLocaleString("fr-FR")}${unit}`;
}

export const STATUS_LABELS: Record<Subscription["status"], string> = {
    trialing: "Essai gratuit",
    active: "Actif",
    past_due: "Paiement en retard",
    suspended: "Suspendu",
    canceled: "Résilié",
};

export const BLOCKED_REASON_LABELS: Record<string, string> = {
    trial_expired: "Votre essai gratuit est terminé : choisissez une offre pour continuer à appeler.",
    minutes_exhausted: "Toutes les minutes incluses dans votre offre sont utilisées pour cette période.",
    payment_overdue: "Le dernier paiement a échoué et le délai de grâce est dépassé.",
    subscription_suspended: "Votre abonnement est suspendu.",
    subscription_canceled: "Votre abonnement est résilié.",
};

export const FEATURE_LABELS: Record<string, string> = {
    local_ai: "IA 100 % locale (données hébergées sur la plateforme)",
    contact_center: "Centre d'appels humain (files d'attente, softphone)",
    campaigns: "Campagnes d'appels sortants",
    api_access: "Accès API et webhooks",
    white_label: "Marque blanche",
    custom_voices: "Voix et langues personnalisées",
};

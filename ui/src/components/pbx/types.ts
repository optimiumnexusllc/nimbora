/** Shapes of GET /pbx/inventory and /pbx/call-logs (free-form JSON in OpenAPI). */
export type PbxUser = {
    id?: number | null;
    uuid: string;
    name: string;
    extension: string | null;
    email: string | null;
    enabled: boolean;
    login?: string | null;
};
export type PbxQueue = {
    id: number;
    name: string;
    extensions: string[];
    members: number;
    agent_ids?: number[];
    wait_time_threshold?: number | null;
    overflow?: { workflow_id: number; workflow_name: string | null } | null;
};
export type PbxAgent = {
    id: number;
    number: string;
    name: string;
    logged: boolean;
    paused: boolean;
    paused_reason: string | null;
    extension: string | null;
};
export type PbxNumber = {
    number: string;
    incall_id: number;
    description: string | null;
    destination: string;
    ai_workflow_id: number | null;
    ai_workflow_name: string | null;
    schedules?: string[];
    destination_type?: string | null;
    destination_target_id?: number | null;
};
export type PbxCall = {
    call_id: string;
    caller: string | null;
    caller_name: string | null;
    peer: string | null;
    peer_name: string | null;
    status: string | null;
    direction: string | null;
    since: string | null;
    on_hold: boolean;
};
export type PbxInventory = {
    users: PbxUser[];
    queues: PbxQueue[];
    agents: PbxAgent[];
    numbers: PbxNumber[];
    calls: PbxCall[];
    errors: Record<string, string>;
};
export type PbxCallLog = {
    id: number;
    start: string | null;
    answered: boolean;
    duration: number | null;
    direction: string | null;
    source_name: string | null;
    source: string | null;
    destination_name: string | null;
    destination: string | null;
};

export const DIRECTION_LABELS: Record<string, string> = {
    inbound: "Entrant",
    outbound: "Sortant",
    internal: "Interne",
};

export function elapsed(iso: string | null, now = Date.now()): string {
    if (!iso) return "—";
    const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

/** GET /pbx/menus */
export type MenuChoiceSpec = { digit: string; label: string; type: string; target_id: number | null };
export type MenuSpecShape = {
    greeting_text: string;
    menu_text: string;
    invalid_text: string;
    choices: MenuChoiceSpec[];
    timeout_seconds: number;
    max_tries: number;
    fallback: { type: string; target_id: number | null };
    voice_workflow_id: number | null;
};
export type PbxMenu = {
    id: number;
    name: string;
    spec: MenuSpecShape;
    pbx_ivr_id: number | null;
    published_at: string | null;
    up_to_date: boolean;
    last_error: string | null;
};

/** GET /pbx/trunks and /pbx/outbound-routes */
export type PbxTrunk = {
    id: number;
    label: string;
    technology: string;
    host: string | null;
    username: string | null;
    registration: boolean;
    registered: boolean | null;
    current_calls: number;
    outcalls: string[];
    caller_id_format: string | null;
};
export type DialRule = { pattern: string; strip_digits: number; prefix: string; external_prefix: string; caller_id: string };
export type PbxOutboundRoute = {
    id: number;
    name: string;
    enabled: boolean;
    internal_caller_id: boolean;
    trunks: { id: number; label: string }[];
    rules: DialRule[];
};
export type PatternPreset = { id: string; label: string; pattern: string };

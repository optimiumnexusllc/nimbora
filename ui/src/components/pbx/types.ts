/** Shapes of GET /pbx/inventory and /pbx/call-logs (free-form JSON in OpenAPI). */
export type PbxUser = { uuid: string; name: string; extension: string | null; email: string | null; enabled: boolean };
export type PbxQueue = { id: number; name: string; extensions: string[]; members: number };
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

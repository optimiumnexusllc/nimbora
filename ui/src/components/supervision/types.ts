export type SpyMode = "listen" | "whisper" | "barge";

/** What the AI agent knew when it handed the caller to a human. */
export type HandoffCard = {
    id: string;
    reason: string | null;
    summary: string | null;
    sentiment: "positive" | "neutral" | "frustrated" | "angry" | null;
    next_step: string | null;
    customer_name: string | null;
};

export type PbxCall = {
    call_id: string;
    user_uuid: string | null;
    user_name: string | null;
    extension: string | null;
    with_number: string | null;
    with_name: string | null;
    direction: string;
    state: "on_call" | "ringing";
    seconds: number;
    on_hold: boolean;
    recording: boolean;
    spyable: boolean;
    handoff?: HandoffCard | null;
};

export type PbxWaitingCaller = {
    position: number;
    number: string | null;
    name: string | null;
    wait_seconds: number;
    handoff?: HandoffCard | null;
};

export type PbxLiveQueue = {
    id: number;
    name: string;
    number: string | null;
    live: boolean;
    waiting: number;
    longest_wait_seconds: number;
    callers: PbxWaitingCaller[];
    agents_available: number;
    agents_on_call: number;
    agents_paused: number;
    agents_logged: number;
    members: number;
    sla_seconds: number;
};

export type PbxLiveAgent = {
    id: number;
    number: string;
    name: string;
    user_uuid: string | null;
    extension: string | null;
    state: "available" | "on_call" | "ringing" | "paused" | "logged_out";
    paused_reason: string | null;
    call: PbxCall | null;
};

export type PbxLive = {
    queues: PbxLiveQueue[];
    agents: PbxLiveAgent[];
    calls: PbxCall[];
    kpis: {
        calls: number;
        waiting: number;
        longest_wait_seconds: number;
        agents_available: number;
        agents_on_call: number;
        agents_paused: number;
        agents_logged_out: number;
    };
    listening: { enabled: boolean; modes: SpyMode[]; supervisors: string[] };
    errors: Record<string, string>;
    at?: string;
    /** Set when the PBX could not be read at all. */
    unavailable?: string;
};

export type ListeningSettings = {
    enabled: boolean;
    modes: SpyMode[];
    supervisors: string[];
    protected: string[];
    notice_acknowledged: boolean;
    sla_seconds: number;
    my_extension?: string | null;
};

export const SENTIMENT_LABELS: Record<NonNullable<HandoffCard["sentiment"]>, { label: string; className: string }> = {
    positive: { label: "satisfait", className: "text-emerald-300" },
    neutral: { label: "neutre", className: "text-muted-foreground" },
    frustrated: { label: "agacé", className: "text-amber-300" },
    angry: { label: "en colère", className: "text-red-300" },
};

export const SPY_LABELS: Record<SpyMode, string> = {
    listen: "Écouter",
    whisper: "Chuchoter",
    barge: "Intervenir",
};

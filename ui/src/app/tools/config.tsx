"use client";

import {
    ArrowLeftRight,
    Calculator,
    CalendarCheck,
    CalendarClock,
    Cog,
    Globe,
    type LucideIcon,
    MessageSquareText,
    Package,
    PhoneForwarded,
    PhoneOff,
    Puzzle,
    Target,
    Ticket as TicketIcon,
} from "lucide-react";
import { type ReactNode } from "react";

import type {
    CalculatorToolDefinition,
    ContextDestinationMappingConfig,
    ContextDestinationRoute,
    ContextDestinationRule,
    EndCallConfig,
    EndCallToolDefinition,
    HttpApiToolDefinition,
    McpToolDefinition,
    ScheduleCallbackConfig,
    ScheduleCallbackToolDefinition,
    TransferAgentConfig,
    TransferAgentToolDefinition,
    TransferCallConfig,
    TransferCallToolDefinition,
} from "@/client/types.gen";
import { createUuid } from "@/lib/uuid";

export type ToolCategory =
    | "http_api"
    | "end_call"
    | "transfer_call"
    | "transfer_agent"
    | "calculator"
    | "schedule_callback"
    | "book_appointment"
    | "send_message"
    | "create_ticket"
    | "search_catalog"
    | "qualify_lead"
    | "native"
    | "integration"
    | "mcp";


export type EndCallMessageType = "none" | "custom" | "audio";
export type TransferDestinationSource = "static" | "dynamic" | "context_mapping" | "smart";

export interface ContextDestinationRouteRow extends ContextDestinationRoute {
    id: string;
}

export interface ContextDestinationRuleRow {
    id: string;
    context_path: string;
    routes: ContextDestinationRouteRow[];
}

export function createContextDestinationRouteRow(
    route?: Partial<ContextDestinationRoute>,
): ContextDestinationRouteRow {
    return {
        id: createUuid(),
        context_value: route?.context_value ?? "",
        destination: route?.destination ?? "",
    };
}

export function createContextDestinationRuleRow(
    rule?: Partial<ContextDestinationRule>,
): ContextDestinationRuleRow {
    return {
        id: createUuid(),
        context_path: rule?.context_path ?? "",
        routes: (rule?.routes ?? [{}]).map(createContextDestinationRouteRow),
    };
}

/** Normalize a stored mapping (ordered or legacy single-rule) into editable rows. */
export function contextMappingToRuleRows(
    mapping?: ContextDestinationMappingConfig | null,
): ContextDestinationRuleRow[] {
    if (!mapping) return [];
    const rules = mapping.rules?.length
        ? mapping.rules
        : mapping.context_path || mapping.routes?.length
            ? [{ context_path: mapping.context_path || "", routes: mapping.routes || [] }]
            : [];
    return rules.map(createContextDestinationRuleRow);
}

export function ruleRowsToContextMappingRules(
    rows: ContextDestinationRuleRow[],
): ContextDestinationRule[] {
    return rows.map((rule) => ({
        context_path: rule.context_path.trim(),
        routes: rule.routes.map((route) => ({
            context_value: route.context_value.trim(),
            destination: route.destination.trim(),
        })),
    }));
}

export interface ToolCategoryConfig {
    value: ToolCategory;
    label: string;
    description: string;
    icon: LucideIcon;
    iconName: string; // String name for storing in database
    iconColor: string;
    disabled?: boolean;
    autoFill?: {
        name: string;
        description: string;
    };
}

export const TOOL_CATEGORIES: ToolCategoryConfig[] = [
    {
        value: "http_api",
        label: "External HTTP API",
        description: "Make HTTP requests to external APIs",
        icon: Globe,
        iconName: "globe",
        iconColor: "#3B82F6",
    },
    {
        value: "end_call",
        label: "End Call",
        description: "End the call when conditions are met",
        icon: PhoneOff,
        iconName: "phone-off",
        iconColor: "#EF4444",
        autoFill: {
            name: "End Call",
            description: "End the call when either user asks to disconnect the call, or when you believe its time to end the conversation",
        },
    },
    {
        value: "transfer_call",
        label: "Transfer Call",
        description: "Transfer the call to another phone number (Twilio, Plivo)",
        icon: PhoneForwarded,
        iconName: "phone-forwarded",
        iconColor: "#10B981",
        autoFill: {
            name: "Transfer Call",
            description: "Transfer the caller to another phone number when requested",
        },
    },
    {
        value: "transfer_agent",
        label: "Transfer To Agent",
        description: "Hand the live call to another agent, without dropping the caller",
        icon: ArrowLeftRight,
        iconName: "arrow-left-right",
        iconColor: "#0EA5E9",
        autoFill: {
            name: "Transfer To Agent",
            description: "Transfer the caller to a specialist agent when their question is outside what you handle",
        },
    },
    {
        value: "calculator",
        label: "Calculator",
        description: "Built-in calculator for arithmetic operations",
        icon: Calculator,
        iconName: "calculator",
        iconColor: "#F59E0B",
        autoFill: {
            name: "Calculator",
            description: "Perform arithmetic calculations (supports +, -, *, /, **, %, and parentheses)",
        },
    },
    {
        value: "schedule_callback",
        label: "Schedule Callback",
        description: "Promise a callback: your team or an AI agent calls the customer back at the time they choose",
        icon: CalendarClock,
        iconName: "calendar-clock",
        iconColor: "#06B6D4",
        autoFill: {
            name: "Schedule Callback",
            description:
                "Schedule a callback when the customer would rather be called back later, or when nobody can help them right now. Ask for the preferred date and time first.",
        },
    },
    {
        value: "book_appointment",
        label: "Book Appointment",
        description: "Offer free slots from a calendar (built-in, CalDAV, Google), book, list and cancel appointments",
        icon: CalendarCheck,
        iconName: "calendar-check",
        iconColor: "#22C55E",
        autoFill: {
            name: "Book Appointment",
            description:
                "Book an appointment when the caller wants one. First find free slots, offer two or three, then book the slot the caller chooses. Also lists or cancels the caller's appointments.",
        },
    },
    {
        value: "send_message",
        label: "Send Message",
        description: "Send the caller an SMS, a WhatsApp message or an e-mail during the call",
        icon: MessageSquareText,
        iconName: "message-square-text",
        iconColor: "#0EA5E9",
        autoFill: {
            name: "Send Message",
            description:
                "Send the caller a written message with information they need to keep (address, link, reference). Ask before sending.",
        },
    },
    {
        value: "create_ticket",
        label: "Create Ticket",
        description: "Open a support ticket (built-in, Zendesk, Freshdesk) and tell callers where their tickets stand",
        icon: TicketIcon,
        iconName: "ticket",
        iconColor: "#F97316",
        autoFill: {
            name: "Create Ticket",
            description:
                "Open a support ticket when the request cannot be solved during the call, then give the caller the ticket number. Also tells callers the status of their tickets.",
        },
    },
    {
        value: "search_catalog",
        label: "Search Catalog",
        description: "Search the company's catalog (products, properties, rooms…) with prices and stock",
        icon: Package,
        iconName: "package",
        iconColor: "#14B8A6",
        autoFill: {
            name: "Search Catalog",
            description:
                "Search our catalog when the caller asks what we offer, a price or whether something is available. Quote only what the search returns.",
        },
    },
    {
        value: "qualify_lead",
        label: "Qualify Lead",
        description: "Record the prospect's need, budget and timeline; leads land in the sales pipeline",
        icon: Target,
        iconName: "target",
        iconColor: "#EAB308",
        autoFill: {
            name: "Qualify Lead",
            description:
                "Record the caller's project as soon as they describe it, then after each new answer (need, budget, timeline, who decides, what interests them). Ask what the tool says is still unknown.",
        },
    },
    {
        value: "mcp",
        label: "MCP Server",
        description: "Connect a customer MCP server; its tools become available to the agent",
        icon: Puzzle,
        iconName: "puzzle",
        iconColor: "#8B5CF6",
    },
    {
        value: "native",
        label: "Native (Coming Soon)",
        description: "Built-in tools like call transfer, DTMF input",
        icon: Cog,
        iconName: "cog",
        iconColor: "#6B7280",
        disabled: true,
    },
    {
        value: "integration",
        label: "Integration (Coming Soon)",
        description: "Third-party integrations like Google Calendar",
        icon: Puzzle,
        iconName: "puzzle",
        iconColor: "#8B5CF6",
        disabled: true,
    },
];

export function getCategoryConfig(category: ToolCategory): ToolCategoryConfig | undefined {
    return TOOL_CATEGORIES.find(c => c.value === category);
}

export function getToolIcon(category: string): LucideIcon {
    const config = TOOL_CATEGORIES.find(c => c.value === category);
    return config?.icon ?? Globe;
}

export function getToolIconColor(category: string, fallbackColor?: string): string {
    const config = TOOL_CATEGORIES.find(c => c.value === category);
    return config?.iconColor ?? fallbackColor ?? "#3B82F6";
}

export function renderToolIcon(category: string, className: string = "w-5 h-5 text-white"): ReactNode {
    const Icon = getToolIcon(category);
    return <Icon className={className} />;
}

export function getToolTypeLabel(category: string): string {
    switch (category) {
        case "end_call":
            return "End Call Tool";
        case "transfer_call":
            return "Transfer Call Tool";
        case "transfer_agent":
            return "Transfer To Agent Tool";
        case "http_api":
            return "HTTP API Tool";
        case "calculator":
            return "Calculator Tool";
        case "schedule_callback":
            return "Schedule Callback Tool";
        case "book_appointment":
            return "Book Appointment Tool";
        case "send_message":
            return "Send Message Tool";
        case "create_ticket":
            return "Create Ticket Tool";
        case "search_catalog":
            return "Search Catalog Tool";
        case "qualify_lead":
            return "Qualify Lead Tool";
        case "native":
            return "Native Tool";
        case "integration":
            return "Integration Tool";
        case "mcp":
            return "MCP Server Tool";
        default:
            return "Tool";
    }
}

export const DEFAULT_END_CALL_REASON_DESCRIPTION =
    "The reason for ending the call (e.g., 'voicemail_detected', 'issue_resolved', 'customer_requested')";

export const DEFAULT_END_CALL_CONFIG: EndCallConfig = {
    endCallReason: false,
};

export const DEFAULT_TRANSFER_AGENT_MESSAGE =
    "Let me connect you with the right person. One moment please.";

export const DEFAULT_TRANSFER_INTRODUCTION_PROMPT =
    "Briefly introduce this caller to the person receiving the transfer. " +
    "Include their reason for calling, essential details, and any explicit " +
    "language preference. Use the caller's preferred language. Keep it to one " +
    "sentence, at most 25 words. Do not invent details.";

export const DEFAULT_TRANSFER_CALL_CONFIG: TransferCallConfig = {
    destination: "",
    timeout: 30,
    introduction_enabled: false,
    introduction_prompt: DEFAULT_TRANSFER_INTRODUCTION_PROMPT,
};

export type ToolDefinition =
    | HttpApiToolDefinition
    | EndCallToolDefinition
    | TransferCallToolDefinition
    | TransferAgentToolDefinition
    | CalculatorToolDefinition
    | ScheduleCallbackToolDefinition
    | McpToolDefinition;

export function createEndCallDefinition(config: EndCallConfig): EndCallToolDefinition {
    return {
        schema_version: 1,
        type: "end_call",
        messages: [],
        config,
    };
}

export function createTransferCallDefinition(config: TransferCallConfig): TransferCallToolDefinition {
    return {
        schema_version: 1,
        type: "transfer_call",
        messages: [],
        config,
    };
}

/**
 * A transfer tool is defined by where it sends the caller, so there is no
 * meaningful empty default — the create dialog collects the destination and
 * builds the definition from it.
 */
export function createTransferAgentDefinition(
    config: TransferAgentConfig,
    messages: NonNullable<TransferAgentToolDefinition["messages"]> = [
        { event: "start", type: "text", text: DEFAULT_TRANSFER_AGENT_MESSAGE },
    ],
): TransferAgentToolDefinition {
    return {
        schema_version: 1,
        type: "transfer_agent",
        messages,
        config,
    };
}

export function createHttpApiDefinition(): HttpApiToolDefinition {
    return {
        schema_version: 1,
        type: "http_api",
        messages: [],
        config: {
            method: "POST",
            url: "",
        },
    };
}

export function createCalculatorDefinition(): CalculatorToolDefinition {
    return {
        schema_version: 1,
        type: "calculator",
        messages: [],
    };
}

export function createScheduleCallbackDefinition(
    config: ScheduleCallbackConfig = { assign_to: "human", default_delay_minutes: 0 },
): ScheduleCallbackToolDefinition {
    return {
        schema_version: 1,
        type: "schedule_callback",
        messages: [],
        config,
    };
}

export const MCP_URL_PATTERN = /^https?:\/\//i;

export function createMcpDefinition(
    url: string,
    credentialUuid: string,
    toolsFilterCsv: string,
): McpToolDefinition {
    return {
        schema_version: 1,
        type: "mcp" as const,
        messages: [],
        config: {
            transport: "streamable_http" as const,
            url: url.trim(),
            credential_uuid: credentialUuid || null,
            tools_filter: toolsFilterCsv
                .split(",")
                .map((s) => s.trim())
                .filter((s) => s.length > 0),
        },
    };
}

export function createToolDefinition(category: ToolCategory): ToolDefinition {
    switch (category) {
        case "end_call":
            return createEndCallDefinition(DEFAULT_END_CALL_CONFIG);
        case "transfer_call":
            return createTransferCallDefinition(DEFAULT_TRANSFER_CALL_CONFIG);
        case "calculator":
            return createCalculatorDefinition();
        case "schedule_callback":
            return createScheduleCallbackDefinition();
        case "book_appointment":
        case "send_message":
        case "create_ticket":
        case "search_catalog":
        case "qualify_lead":
            return { schema_version: 1, type: category, messages: [], config: {} } as unknown as ToolDefinition;
        case "http_api":
        default:
            return createHttpApiDefinition();
    }
}

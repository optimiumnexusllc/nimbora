"""Pydantic schemas for reusable NIMBORA tools.

These models are the single contract for tool creation/update across the
REST API, generated SDKs, and the MCP authoring surface. Field descriptions
are human/API-facing; ``llm_hint`` JSON schema extras are guidance for LLMs
when the same schema is surfaced through MCP or SDK authoring flows.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.enums import ToolCategory

DEFAULT_MCP_TIMEOUT_SECS = 30
DEFAULT_MCP_SSE_READ_TIMEOUT_SECS = 300
MAX_TRANSFER_CALL_DISPOSITION_LENGTH = 64
DEFAULT_TRANSFER_INTRODUCTION_PROMPT = (
    "Briefly introduce this caller to the person receiving the transfer. "
    "Include their reason for calling, essential details, and any explicit "
    "language preference. Use the caller's preferred language. Keep it to one "
    "sentence, at most 25 words. Do not invent details."
)

ToolParameterType = Literal["string", "number", "boolean", "object", "array"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ToolCategoryValue = Literal[
    "http_api",
    "end_call",
    "transfer_call",
    "transfer_agent",
    "calculator",
    "schedule_callback",
    "book_appointment",
    "send_message",
    "create_ticket",
    "native",
    "integration",
    "mcp",
]


def _llm_hint(text: str) -> dict[str, str]:
    return {"llm_hint": text}


class ToolParameter(BaseModel):
    """A parameter that the tool accepts from the model at call time."""

    name: str = Field(
        description="Parameter name used as a key in the tool request body.",
        json_schema_extra=_llm_hint(
            "Use a stable snake_case name the agent can naturally fill."
        ),
    )
    type: ToolParameterType = Field(
        description="JSON type for the parameter value.",
        json_schema_extra=_llm_hint(
            "Allowed values are string, number, boolean, object, and array."
        ),
    )
    description: str = Field(
        description="Description shown to the model for this parameter.",
        json_schema_extra=_llm_hint(
            "Write this as an instruction to the agent: what value to provide and when."
        ),
    )
    required: bool = Field(
        default=True,
        description="Whether this parameter is required when the tool is called.",
    )


class PresetToolParameter(BaseModel):
    """A parameter injected by NIMBORA at runtime."""

    name: str = Field(description="Parameter name used as a key in the request body.")
    type: ToolParameterType = Field(
        description="JSON type for the resolved value.",
        json_schema_extra=_llm_hint(
            "Allowed values are string, number, boolean, object, and array."
        ),
    )
    value_template: str = Field(
        description="Fixed value or template, e.g. {{initial_context.phone_number}}.",
        json_schema_extra=_llm_hint(
            "Use {{initial_context.*}} for call-start context and "
            "{{gathered_context.*}} for values extracted during the call."
        ),
    )
    required: bool = Field(
        default=True,
        description="Whether the parameter must resolve to a non-empty value.",
    )


class HttpApiConfig(BaseModel):
    """Configuration for HTTP API tools."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod = Field(
        description="HTTP method to use for the request.",
        json_schema_extra=_llm_hint("Use one of GET, POST, PUT, PATCH, DELETE."),
    )
    url: str = Field(
        description="Target HTTP or HTTPS URL.",
        json_schema_extra=_llm_hint(
            "Use the final endpoint URL. Authentication belongs in credential_uuid, "
            "not embedded in the URL."
        ),
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Static headers to include with every request.",
        json_schema_extra=_llm_hint(
            "Do not place secrets here. Store secrets in the UI credential manager "
            "and reference them with credential_uuid."
        ),
    )
    credential_uuid: str | None = Field(
        default=None,
        description="Reference to an external credential for request authentication.",
        json_schema_extra=_llm_hint(
            "Use a credential_uuid returned by list_credentials. The MCP flow does "
            "not create credential secrets."
        ),
    )
    parameters: list[ToolParameter] | None = Field(
        default=None,
        description="Parameters the model must provide when calling this tool.",
    )
    preset_parameters: list[PresetToolParameter] | None = Field(
        default=None,
        description=(
            "Parameters injected by NIMBORA from fixed values or workflow context "
            "templates."
        ),
    )
    timeout_ms: int | None = Field(
        default=5000,
        ge=1,
        description="Request timeout in milliseconds.",
    )
    body_template: dict[str, Any] | None = Field(
        default=None,
        description="Optional JSON body template for POST, PUT, and PATCH requests.",
        json_schema_extra=_llm_hint(
            "Use {{parameter_name}} placeholders to position LLM and preset "
            "parameters anywhere in the body, including nested objects and arrays; "
            "also {{initial_context.*}}. A value that is exactly one placeholder "
            "keeps the value's original JSON type. Omit this field to send all "
            "parameters as a flat top-level JSON object. Ignored for GET and DELETE."
        ),
    )
    body_format: Literal["json", "form"] = Field(
        default="json",
        description=(
            "Encoding of the POST, PUT, and PATCH request body: 'json' sends "
            "application/json, 'form' sends application/x-www-form-urlencoded."
        ),
        json_schema_extra=_llm_hint(
            "Use 'form' only for APIs that accept form-encoded bodies and "
            "reject JSON. In form mode, list values repeat the field name once per "
            "item and object values are sent as JSON strings."
        ),
    )

    @field_validator("method", mode="before")
    @classmethod
    def validate_method(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("method must be one of GET, POST, PUT, PATCH, DELETE")
        method = v.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("method must be one of GET, POST, PUT, PATCH, DELETE")
        return method


class EndCallConfig(BaseModel):
    """Configuration for End Call tools."""

    model_config = ConfigDict(extra="forbid")

    endCallReason: bool = Field(
        default=False,
        description=(
            "When enabled, the model must provide a reason for ending the call. "
            "The reason is set as call disposition and added to call tags."
        ),
    )
    endCallReasonDescription: str | None = Field(
        default=None,
        description=(
            "Description shown to the model for the reason parameter. Used only "
            "when endCallReason is enabled."
        ),
    )


class HttpTransferResolverConfig(BaseModel):
    """HTTP endpoint used to resolve transfer destination at call time."""

    type: Literal["http"] = Field(default="http", description="Resolver type.")
    url: str = Field(description="HTTP or HTTPS endpoint for transfer resolution.")
    headers: dict[str, str] | None = Field(
        default=None,
        description="Static headers to include with every resolver request.",
    )
    credential_uuid: str | None = Field(
        default=None,
        description="Reference to an external credential for resolver authentication.",
    )
    timeout_ms: int = Field(
        default=3000,
        ge=500,
        le=5000,
        description="Resolver request timeout in milliseconds.",
    )
    wait_message: str | None = Field(
        default=None,
        description="Optional short message played while NIMBORA resolves routing.",
    )
    parameters: list[ToolParameter] | None = Field(
        default=None,
        description="Parameters the model may provide when calling this transfer tool.",
    )
    preset_parameters: list[PresetToolParameter] | None = Field(
        default=None,
        description=(
            "Parameters injected by NIMBORA from fixed values or workflow context "
            "templates."
        ),
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not isinstance(v, str) or not v.startswith(("http://", "https://")):
            raise ValueError("config.resolver.url must be an http(s) URL")
        return v


class ContextDestinationRoute(BaseModel):
    """Map one context value to a transfer destination."""

    context_value: str = Field(
        min_length=1,
        max_length=255,
        description="Context value that selects this destination.",
    )
    destination: str = Field(
        min_length=1,
        max_length=255,
        description=(
            "VICIdial in-group, SIP endpoint, E.164 phone number, or context "
            "template used when this route matches."
        ),
    )

    @field_validator("context_value", "destination")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("mapping values cannot be blank")
        return stripped


class ContextDestinationRule(BaseModel):
    """One context lookup with its value-to-destination routes."""

    context_path: str = Field(
        min_length=1,
        max_length=255,
        description=(
            "Context path used for routing. An unprefixed path checks gathered "
            "context first, then initial context; use initial_context.* or "
            "gathered_context.* to select one explicitly."
        ),
    )
    routes: list[ContextDestinationRoute] = Field(min_length=1, max_length=100)

    @field_validator("context_path")
    @classmethod
    def strip_context_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("context path cannot be blank")
        return stripped

    @model_validator(mode="after")
    def validate_unique_values(self):
        values = [route.context_value.casefold() for route in self.routes]
        if len(values) != len(set(values)):
            raise ValueError("context mapping values must be unique")
        return self


class ContextDestinationMappingConfig(BaseModel):
    """Resolve a transfer destination from gathered or initial context.

    Rules are evaluated in order. The first rule whose context value matches
    one of its routes wins; ``fallback_destination`` applies only when no rule
    matched. Destinations may be provider-native values or context templates.
    """

    rules: list[ContextDestinationRule] | None = Field(
        default=None,
        description="Ordered routing rules evaluated top to bottom; first match wins.",
    )
    context_path: str | None = Field(
        default=None,
        exclude=True,
        description=(
            "Deprecated single-rule context path. Use rules instead; accepted for "
            "backward compatibility."
        ),
    )
    routes: list[ContextDestinationRoute] | None = Field(
        default=None,
        exclude=True,
        description=(
            "Deprecated single-rule routes. Use rules instead; accepted for "
            "backward compatibility."
        ),
    )
    fallback_destination: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Optional provider-native destination or context template used when "
            "no rule matched."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def fold_single_rule(cls, data: Any) -> Any:
        """Accept the legacy single-rule shape (context_path plus routes)."""
        if not isinstance(data, dict) or data.get("rules") is not None:
            return data
        if "context_path" not in data and "routes" not in data:
            return data
        folded = {
            key: value
            for key, value in data.items()
            if key not in ("context_path", "routes")
        }
        folded["rules"] = [
            {"context_path": data.get("context_path"), "routes": data.get("routes")}
        ]
        return folded

    @model_validator(mode="after")
    def require_rules(self):
        if not self.rules:
            raise ValueError("context mapping rules must contain at least one rule")
        if len(self.rules) > 20:
            raise ValueError("context mapping rules cannot contain more than 20 rules")
        return self

    @field_validator("fallback_destination")
    @classmethod
    def normalize_fallback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TransferCallConfig(BaseModel):
    """Configuration for Transfer Call tools."""

    model_config = ConfigDict(extra="forbid")

    introduction_enabled: bool = Field(
        default=False,
        description=(
            "Play a generated introduction in the agent's voice to both parties "
            "before connecting them. Supported for Twilio calls with a TTS "
            "provider. Realtime speech-to-speech agents and synthesis failures "
            "skip the introduction."
        ),
    )
    introduction_prompt: str = Field(
        default=DEFAULT_TRANSFER_INTRODUCTION_PROMPT,
        max_length=2000,
        description="Instructions for the transfer introduction, including language.",
    )
    destination_source: Literal["static", "dynamic", "context_mapping"] = Field(
        default="static",
        description=(
            "Whether the destination is static/template, resolved by HTTP, or "
            "selected by ordered gathered/initial-context mapping rules."
        ),
    )
    destination: str = Field(
        default="",
        description=(
            "Phone number, SIP endpoint, or template to transfer the call to, e.g. "
            "+1234567890, PJSIP/1234, or {{initial_context.transfer_destination}}."
        ),
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Maximum seconds to wait for the destination to answer.",
    )
    call_disposition: str | None = Field(
        default=None,
        max_length=MAX_TRANSFER_CALL_DISPOSITION_LENGTH,
        description=(
            "Optional disposition to record after a successful transfer. When "
            "omitted, NIMBORA records its provider-specific transfer default."
        ),
    )
    parameters: list[ToolParameter] | None = Field(
        default=None,
        description=(
            "Parameters the model may provide when calling this transfer tool, "
            "for example state, department, or transfer reason."
        ),
    )
    resolver: HttpTransferResolverConfig | None = Field(
        default=None,
        description="Optional resolver that determines transfer routing at call time.",
    )
    context_mapping: ContextDestinationMappingConfig | None = Field(
        default=None,
        description="Optional ordered context-to-destination routing rules.",
    )

    @field_validator("call_disposition", mode="before")
    @classmethod
    def normalize_call_disposition(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_destination_source_config(self):
        if self.destination_source == "dynamic" and self.resolver is None:
            raise ValueError(
                "config.resolver is required when destination_source is dynamic"
            )
        if (
            self.destination_source == "context_mapping"
            and self.context_mapping is None
        ):
            raise ValueError(
                "config.context_mapping is required when destination_source is "
                "context_mapping"
            )
        return self


class McpToolConfig(BaseModel):
    """Configuration for a customer MCP server tool definition."""

    transport: Literal["streamable_http"] = Field(
        default="streamable_http",
        description="MCP transport protocol.",
    )
    url: str = Field(
        description="MCP server URL. Must use http:// or https://.",
        json_schema_extra=_llm_hint("Use the server's streamable HTTP MCP endpoint."),
    )
    credential_uuid: str | None = Field(
        default=None,
        description="Reference to an external credential for MCP server auth.",
        json_schema_extra=_llm_hint(
            "Use a credential_uuid returned by list_credentials. Credentials are "
            "created by the user in the UI."
        ),
    )
    tools_filter: list[str] = Field(
        default_factory=list,
        description="Allowlist of MCP tool names to expose. Empty exposes all tools.",
        json_schema_extra=_llm_hint(
            "Use exact MCP tool names from the remote server catalog when you need "
            "to restrict the exposed tools."
        ),
    )
    timeout_secs: int = Field(
        default=DEFAULT_MCP_TIMEOUT_SECS,
        ge=0,
        description="Connection timeout in seconds.",
    )
    sse_read_timeout_secs: int = Field(
        default=DEFAULT_MCP_SSE_READ_TIMEOUT_SECS,
        ge=0,
        description="SSE read timeout in seconds.",
    )
    discovered_tools: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Server-managed cache of the MCP server's tool catalog "
            "[{name, description}]. Populated best-effort by the backend."
        ),
        json_schema_extra=_llm_hint("Do not author this field; the server fills it."),
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not isinstance(v, str) or not v.startswith(("http://", "https://")):
            raise ValueError("config.url must be an http(s) URL")
        return v

    @field_validator("tools_filter")
    @classmethod
    def validate_tools_filter(cls, v: list[str]) -> list[str]:
        if not all(isinstance(tool_name, str) for tool_name in v):
            raise ValueError("config.tools_filter must be a list of strings")
        return v


class ToolMessageText(BaseModel):
    """A literal phrase spoken by the agent's TTS voice."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    type: Literal["text"]
    text: str = Field(min_length=1)


class ToolMessageAudio(BaseModel):
    """An organization-owned recording, referenced by its immutable primary key."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["audio"]
    recording_id: int = Field(gt=0)


class ToolStartTextMessage(ToolMessageText):
    event: Literal["start"]


class ToolStartAudioMessage(ToolMessageAudio):
    event: Literal["start"]


class ToolDelayedTextMessage(ToolMessageText):
    event: Literal["delayed"]
    after_ms: int = Field(gt=0, le=120000)


class ToolDelayedAudioMessage(ToolMessageAudio):
    event: Literal["delayed"]
    after_ms: int = Field(gt=0, le=120000)


ToolMessage = (
    ToolStartTextMessage
    | ToolStartAudioMessage
    | ToolDelayedTextMessage
    | ToolDelayedAudioMessage
)
ToolMessages = list[ToolMessage]


class ToolDefinitionBase(BaseModel):
    """Shared message format; supported events depend on the tool's behavior."""

    schema_version: int = Field(default=1, description="Schema version.")
    messages: ToolMessages = Field(
        default_factory=list,
        max_length=220,
        description=(
            "Configured speech. An empty list disables announcements. HTTP/MCP "
            "choose one start entry and one entry per delayed timing at random. "
            "End-call and transfer tools support one start entry only."
        ),
    )

    @model_validator(mode="after")
    def validate_messages(self):
        tool_type = self.type
        if tool_type == "calculator" and self.messages:
            raise ValueError("Calculator tools do not support messages")
        if tool_type == "schedule_callback" and self.messages:
            raise ValueError("Schedule callback tools do not support messages")
        if tool_type in {"end_call", "transfer_call", "transfer_agent"}:
            if len(self.messages) > 1 or any(m.event != "start" for m in self.messages):
                raise ValueError("This tool supports at most one start message")
            if tool_type == "transfer_agent" and any(
                m.type != "text" for m in self.messages
            ):
                raise ValueError("Agent transfer supports text messages only")
            if tool_type == "transfer_agent" and any(
                len(m.text) > 500 for m in self.messages
            ):
                raise ValueError(
                    "Agent-transfer messages must be at most 500 characters"
                )
        counts: dict[int, int] = {}
        for message in self.messages:
            timing = message.after_ms if message.event == "delayed" else 0
            counts[timing] = counts.get(timing, 0) + 1
        if any(count > 20 for count in counts.values()):
            raise ValueError("Each event and timing supports at most 20 variants")
        if len(counts.keys() - {0}) > 10:
            raise ValueError("At most 10 delayed timings are supported")
        return self


class HttpApiToolDefinition(ToolDefinitionBase):
    """Tool definition for HTTP API tools."""

    type: Literal["http_api"] = Field(description="Tool type.")
    config: HttpApiConfig = Field(description="HTTP API configuration.")


class EndCallToolDefinition(ToolDefinitionBase):
    """Tool definition for End Call tools."""

    type: Literal["end_call"] = Field(description="Tool type.")
    config: EndCallConfig = Field(description="End Call configuration.")


class TransferCallToolDefinition(ToolDefinitionBase):
    """Tool definition for Transfer Call tools."""

    type: Literal["transfer_call"] = Field(description="Tool type.")
    config: TransferCallConfig = Field(description="Transfer Call configuration.")


TransferGreetingMode = Literal["start_greeting", "continue", "introduce_and_continue"]


class TransferAgentConfig(BaseModel):
    """Configuration for Transfer Agent tools.

    One tool, one destination. An agent that can hand the caller to several
    places gets several of these tools, and the model chooses between them the
    way it chooses between any other tools -- by their names and descriptions.
    That keeps the routing decision in the one place the model already reasons
    about, and leaves nothing to configure here but where the call goes.

    Most of how a handoff sounds is fixed: the caller hears a ringer while the
    next agent is prepared. The handover line is configurable because it is
    caller-facing and NIMBORA runs in more than one language, and so is how the
    next agent opens: an agent that greets callers on its own number should
    not re-introduce itself mid-conversation, and one that only ever answers
    handoffs needs a line of its own before it picks the conversation up.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: int = Field(
        description=(
            "Id of the NIMBORA agent to transfer to. Must be in the same "
            "organization, and must not be a speech-to-speech agent."
        ),
        json_schema_extra=_llm_hint(
            "Name the tool after this agent, e.g. 'Transfer to Billing', and "
            "describe when to use it -- that is what the model routes on."
        ),
    )
    greeting_mode: TransferGreetingMode = Field(
        default="start_greeting",
        description=(
            "How the destination agent opens. 'start_greeting' plays its Start "
            "Call greeting and waits for the caller. 'continue' skips the "
            "greeting and opens with a reply generated from the handover note. "
            "'introduce_and_continue' speaks the introduction in the "
            "destination's own voice and then opens with a generated reply, so "
            "the caller hears who picked up without having to repeat themselves."
        ),
    )
    introduction: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "What the destination agent says as it takes over, in its own voice, "
            "before its first generated reply. Required with greeting_mode "
            "'introduce_and_continue' and not accepted otherwise. Supports "
            "template variables."
        ),
    )

    @model_validator(mode="after")
    def _introduction_matches_greeting_mode(self):
        introduces = self.greeting_mode == "introduce_and_continue"
        if introduces and not (self.introduction and self.introduction.strip()):
            raise ValueError(
                "introduction is required when greeting_mode is "
                "'introduce_and_continue'"
            )
        if not introduces and self.introduction is not None:
            raise ValueError(
                "introduction is only accepted when greeting_mode is "
                "'introduce_and_continue'"
            )
        return self


class TransferAgentToolDefinition(ToolDefinitionBase):
    """Tool definition for Transfer Agent tools."""

    type: Literal["transfer_agent"] = Field(description="Tool type.")
    config: TransferAgentConfig = Field(description="Transfer Agent configuration.")
    messages: ToolMessages = Field(
        default_factory=lambda: [
            ToolStartTextMessage(
                event="start",
                type="text",
                text="Let me connect you with the right person. One moment please.",
            )
        ],
        max_length=220,
        description=(
            "One start text message, with template variables supported. Omit to "
            "use the default handover line, or send an empty list for a silent handoff."
        ),
    )


class CalculatorToolDefinition(ToolDefinitionBase):
    """Tool definition for Calculator tools."""

    type: Literal["calculator"] = Field(description="Tool type.")


class ScheduleCallbackConfig(BaseModel):
    """Configuration for Schedule Callback tools.

    The model fills the time and the reason during the call; who calls back
    is fixed here: the human team (optionally a given queue) or an AI agent.
    """

    model_config = ConfigDict(extra="forbid")

    assign_to: Literal["human", "ai"] = Field(
        default="human",
        description=(
            "Who calls the customer back: 'human' puts the callback in the "
            "contact-center team's list, 'ai' has workflow_id place the call "
            "automatically at the scheduled time."
        ),
    )
    queue_slug: str | None = Field(
        default=None,
        max_length=48,
        description="Contact-center queue whose agents should call back (human).",
    )
    workflow_id: int | None = Field(
        default=None,
        description="NIMBORA agent that places the callback. Required with 'ai'.",
    )
    default_delay_minutes: int = Field(
        default=0,
        ge=0,
        le=10080,
        description="Delay applied when the customer asks to be called 'asap'.",
    )

    @model_validator(mode="after")
    def _ai_needs_agent(self):
        if self.assign_to == "ai" and not self.workflow_id:
            raise ValueError("workflow_id is required when assign_to is 'ai'")
        if self.assign_to == "human" and self.workflow_id is not None:
            raise ValueError("workflow_id is only accepted when assign_to is 'ai'")
        return self


class ScheduleCallbackToolDefinition(ToolDefinitionBase):
    """Tool definition for Schedule Callback tools."""

    type: Literal["schedule_callback"] = Field(description="Tool type.")
    config: ScheduleCallbackConfig = Field(
        default_factory=ScheduleCallbackConfig,
        description="Schedule Callback configuration.",
    )


_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-4]):[0-5]\d$")


def _default_opening_hours() -> dict[str, list[str]]:
    return {day: ["09:00-12:00", "14:00-18:00"] for day in _WEEKDAYS[:5]}


class BookAppointmentConfig(BaseModel):
    """Book appointments in a calendar during the call.

    ``nimbora`` keeps the agenda in NIMBORA (Activité → Rendez-vous);
    ``caldav`` works with Nextcloud, iCloud, Zimbra, SOGo, Radicale… (basic
    auth credential); ``google`` uses a service-account credential with the
    calendar shared to it.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["nimbora", "caldav", "google"] = "nimbora"
    credential_uuid: str | None = Field(default=None, max_length=36)
    calendar_url: str | None = Field(
        default=None, max_length=1000, description="CalDAV calendar collection URL."
    )
    calendar_id: str | None = Field(
        default=None, max_length=255, description="Google calendar ID (e-mail form)."
    )
    calendar_name: str | None = Field(default=None, max_length=128)
    timezone: str | None = Field(default=None, max_length=64)
    slot_minutes: int = Field(default=30, ge=5, le=480)
    buffer_minutes: int = Field(default=0, ge=0, le=240)
    min_notice_minutes: int = Field(default=60, ge=0, le=20160)
    horizon_days: int = Field(default=30, ge=1, le=365)
    opening_hours: dict[str, list[str]] = Field(default_factory=_default_opening_hours)
    allow_cancel: bool = True

    @field_validator("opening_hours")
    @classmethod
    def _hours(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        cleaned: dict[str, list[str]] = {}
        for day, ranges in value.items():
            if day not in _WEEKDAYS:
                raise ValueError(f"Unknown day '{day}' (use mon..sun)")
            for item in ranges:
                if not _RANGE_RE.match(item) or item[:5] >= item[6:]:
                    raise ValueError(f"Invalid opening range '{item}' (HH:MM-HH:MM)")
            cleaned[day] = list(ranges)
        return cleaned

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        if value:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(value)
            except Exception as exc:
                raise ValueError(f"Unknown time zone '{value}'") from exc
        return value

    @model_validator(mode="after")
    def _provider_fields(self):
        if self.provider == "caldav" and not (
            self.calendar_url and self.credential_uuid
        ):
            raise ValueError("CalDAV needs calendar_url and a basic-auth credential")
        if self.provider == "caldav" and not self.calendar_url.startswith(
            ("https://", "http://")
        ):
            raise ValueError("calendar_url must be an http(s) URL")
        if self.provider == "google" and not (
            self.calendar_id and self.credential_uuid
        ):
            raise ValueError(
                "Google Calendar needs calendar_id and a service-account credential"
            )
        return self


class BookAppointmentToolDefinition(ToolDefinitionBase):
    type: Literal["book_appointment"] = Field(description="Tool type.")
    config: BookAppointmentConfig = Field(default_factory=BookAppointmentConfig)


class SendMessageConfig(BaseModel):
    """Send an SMS, a WhatsApp message or an e-mail during the call.

    ``twilio`` (SMS / WhatsApp, basic-auth credential: Account SID + Auth
    Token), ``http`` (any SMS gateway: POST JSON {to, from, message, channel}
    with the tool credential), ``smtp`` (e-mail, basic-auth credential).
    """

    model_config = ConfigDict(extra="forbid")

    channel: Literal["sms", "whatsapp", "email"] = "sms"
    provider: Literal["twilio", "http", "smtp"] = "twilio"
    credential_uuid: str | None = Field(default=None, max_length=36)
    sender: str = Field(
        default="", max_length=255, description="Number, WhatsApp number or e-mail."
    )
    gateway_url: str | None = Field(default=None, max_length=1000)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    subject: str | None = Field(default=None, max_length=255)
    template: str | None = Field(
        default=None,
        max_length=1600,
        description="Message text with {{variables}}; the agent fills {{details}}.",
    )
    allow_other_recipient: bool = Field(
        default=False,
        description="Let the agent send to a number the caller gives (SMS/WhatsApp).",
    )
    max_per_call: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def _provider_fields(self):
        if self.channel == "email" and self.provider != "smtp":
            raise ValueError("E-mail is sent with the smtp provider")
        if self.channel != "email" and self.provider == "smtp":
            raise ValueError("SMS and WhatsApp use the twilio or http provider")
        # Missing sender, credential, host or gateway are reported when the
        # tool runs: tools are created first, configured next.
        if self.gateway_url and not self.gateway_url.startswith(
            ("https://", "http://")
        ):
            raise ValueError("gateway_url must be an http(s) URL")
        return self


class SendMessageToolDefinition(ToolDefinitionBase):
    type: Literal["send_message"] = Field(description="Tool type.")
    config: SendMessageConfig = Field(default_factory=SendMessageConfig)


class CreateTicketConfig(BaseModel):
    """Open (and follow up) support tickets during the call.

    ``nimbora`` is the built-in helpdesk (Activité → Tickets); ``zendesk``
    (credential: basic auth "email/token" + API token) and ``freshdesk``
    (basic auth: API key + "X") push the ticket to those helpdesks.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["nimbora", "zendesk", "freshdesk"] = "nimbora"
    credential_uuid: str | None = Field(default=None, max_length=36)
    domain: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[a-z0-9][a-z0-9-]*\.(zendesk|freshdesk)\.com$",
        description="e.g. acme.zendesk.com",
    )
    categories: list[str] = Field(default_factory=list, max_length=30)
    default_priority: Literal["low", "normal", "high", "urgent"] = "normal"
    allow_lookup: bool = Field(
        default=True, description="Let callers ask the status of their tickets."
    )

    @model_validator(mode="after")
    def _provider_fields(self):
        if self.provider != "nimbora":
            if not (self.domain and self.credential_uuid):
                raise ValueError(f"{self.provider} needs a domain and a credential")
            if not self.domain.endswith(f".{self.provider}.com"):
                raise ValueError(f"The domain must end with .{self.provider}.com")
        return self


class CreateTicketToolDefinition(ToolDefinitionBase):
    type: Literal["create_ticket"] = Field(description="Tool type.")
    config: CreateTicketConfig = Field(default_factory=CreateTicketConfig)


class McpToolDefinition(ToolDefinitionBase):
    """Persisted MCP tool definition."""

    type: Literal["mcp"] = Field(description="Tool type.")
    config: McpToolConfig = Field(description="MCP server configuration.")


ToolDefinition = Annotated[
    HttpApiToolDefinition
    | EndCallToolDefinition
    | TransferCallToolDefinition
    | TransferAgentToolDefinition
    | CalculatorToolDefinition
    | ScheduleCallbackToolDefinition
    | BookAppointmentToolDefinition
    | SendMessageToolDefinition
    | CreateTicketToolDefinition
    | McpToolDefinition,
    Field(discriminator="type"),
]


class CreateToolRequest(BaseModel):
    """Request schema for creating a reusable tool."""

    name: str = Field(
        max_length=255,
        description="Display name for the tool.",
        json_schema_extra=_llm_hint(
            "Use a concise action-oriented name; this influences the function "
            "name shown to the agent."
        ),
    )
    description: str | None = Field(
        default=None,
        description="Description shown to the agent when deciding whether to call it.",
        json_schema_extra=_llm_hint(
            "State exactly when the agent should call the tool and what result it gets."
        ),
    )
    category: ToolCategoryValue = Field(
        default=ToolCategory.HTTP_API.value,
        description="Tool category. Must match definition.type.",
    )
    icon: str | None = Field(
        default="globe", max_length=50, description="Lucide icon identifier."
    )
    icon_color: str | None = Field(
        default="#3B82F6", max_length=7, description="Hex color for the tool icon."
    )
    definition: ToolDefinition = Field(description="Typed tool definition.")

    @model_validator(mode="before")
    @classmethod
    def default_category_from_definition(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("category"):
            return data
        definition = data.get("definition")
        if isinstance(definition, dict) and definition.get("type"):
            return {**data, "category": definition["type"]}
        return data

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid_categories = [c.value for c in ToolCategory]
        if v not in valid_categories:
            raise ValueError(
                f"Invalid category '{v}'. Must be one of: {', '.join(valid_categories)}"
            )
        return v

    @model_validator(mode="after")
    def validate_category_matches_definition(self) -> CreateToolRequest:
        definition_type = self.definition.type
        if self.category != definition_type:
            raise ValueError(
                f"category '{self.category}' must match definition.type "
                f"'{definition_type}'"
            )
        return self


class UpdateToolRequest(BaseModel):
    """Request schema for updating a reusable tool."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=50)
    icon_color: str | None = Field(default=None, max_length=7)
    definition: ToolDefinition | None = None
    status: str | None = None


class CreatedByResponse(BaseModel):
    """Response schema for the user who created a tool."""

    id: int
    provider_id: str


class ToolResponse(BaseModel):
    """Response schema for a reusable tool."""

    id: int
    tool_uuid: str
    name: str
    description: str | None
    category: str
    icon: str | None
    icon_color: str | None
    status: str
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None
    created_by: CreatedByResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class McpRefreshResponse(BaseModel):
    """Result of re-discovering an MCP server's tool catalog."""

    tool_uuid: str
    discovered_tools: list = Field(default_factory=list)
    error: str | None = None


class ToolTestRequest(BaseModel):
    """Request body for testing an HTTP API tool outside a live call."""

    llm_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Values for parameters normally supplied by the model.",
    )
    preset_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Resolved values for parameters normally supplied from presets.",
    )


class ToolTestResponse(BaseModel):
    """Result of testing an HTTP API tool."""

    status: str
    status_code: int | None = None
    data: Any | None = None
    error: str | None = None
    hint: str | None = None
    request_method: str
    request_url: str
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: dict[str, Any] | None = None
    request_params: dict[str, Any] | None = None
    duration_ms: int

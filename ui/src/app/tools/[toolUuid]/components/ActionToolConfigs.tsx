"use client";

import { CalendarCheck, Loader2, MessageSquareText, Package, Target, Ticket } from "lucide-react";
import { useState } from "react";

import { previewSlotsApiV1ActionsCalendarsToolUuidPreviewPost } from "@/client/sdk.gen";
import type { BookAppointmentConfig, CreateTicketConfig, QualifyLeadConfig, SearchCatalogConfig, SendMessageConfig } from "@/client/types.gen";
import { CredentialSelector } from "@/components/http";
import { Badge, badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

interface CommonProps {
    name: string;
    onNameChange: (name: string) => void;
    description: string;
    onDescriptionChange: (description: string) => void;
}

function NameAndDescription({ name, onNameChange, description, onDescriptionChange, hint }: CommonProps & { hint: string }) {
    return (
        <>
            <div className="space-y-2">
                <Label htmlFor="tool-name">Tool Name</Label>
                <Input id="tool-name" value={name} onChange={(e) => onNameChange(e.target.value)} />
            </div>
            <div className="space-y-2">
                <Label htmlFor="tool-description">Description</Label>
                <p className="text-xs text-muted-foreground">{hint}</p>
                <Textarea
                    id="tool-description"
                    rows={3}
                    value={description}
                    onChange={(e) => onDescriptionChange(e.target.value)}
                />
            </div>
        </>
    );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
    return (
        <div className="space-y-2">
            <Label>{label}</Label>
            {children}
            {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
    );
}

// --------------------------------------------------------------- calendar

const DAYS: { key: string; label: string }[] = [
    { key: "mon", label: "Lundi" },
    { key: "tue", label: "Mardi" },
    { key: "wed", label: "Mercredi" },
    { key: "thu", label: "Jeudi" },
    { key: "fri", label: "Vendredi" },
    { key: "sat", label: "Samedi" },
    { key: "sun", label: "Dimanche" },
];

export const DEFAULT_OPENING_HOURS: Record<string, string[]> = Object.fromEntries(
    DAYS.slice(0, 5).map((d) => [d.key, ["09:00-12:00", "14:00-18:00"]]),
);

/** "09:00-12:00, 14:00-18:00" <-> ["09:00-12:00", "14:00-18:00"] */
export function parseRanges(text: string): string[] {
    const point = (value: string): string | null => {
        const match = value.trim().match(/^(\d{1,2})(?:\s*[:hH]\s*(\d{2})?)?$/);
        if (!match) return null;
        return `${match[1].padStart(2, "0")}:${match[2] ?? "00"}`;
    };
    return text
        .split(/[,;]/)
        .map((range) => range.split("-"))
        .filter((parts) => parts.length === 2)
        .map(([from, to]) => [point(from), point(to)])
        .filter((pair): pair is [string, string] => Boolean(pair[0] && pair[1]))
        .map(([from, to]) => `${from}-${to}`);
}

export function BookAppointmentToolConfig({
    toolUuid,
    config,
    onChange,
    ...common
}: CommonProps & {
    toolUuid: string;
    config: BookAppointmentConfig;
    onChange: (config: BookAppointmentConfig) => void;
}) {
    const set = (patch: Partial<BookAppointmentConfig>) => onChange({ ...config, ...patch });
    const hours = config.opening_hours ?? DEFAULT_OPENING_HOURS;
    const provider = config.provider ?? "nimbora";
    const [preview, setPreview] = useState<{ loading: boolean; slots?: { label: string }[]; error?: string } | null>(
        null,
    );

    const testCalendar = async () => {
        setPreview({ loading: true });
        const response = await previewSlotsApiV1ActionsCalendarsToolUuidPreviewPost({ path: { tool_uuid: toolUuid } });
        if (response.error || !response.data) {
            setPreview({ loading: false, error: detailFromError(response.error, "Test impossible") });
            return;
        }
        setPreview({
            loading: false,
            slots: (response.data.slots ?? []).map((s) => ({ label: String(s.label ?? "") })),
            error: response.data.status === "ok" ? undefined : (response.data.error ?? "Aucun créneau"),
        });
    };

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <CalendarCheck className="h-5 w-5" />
                    Calendar
                </CardTitle>
                <CardDescription>
                    The agent offers free slots read from the calendar, books the one the caller picks, and can list or
                    cancel the caller&apos;s appointments. Bookings appear in Activité → Rendez-vous.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <NameAndDescription
                    {...common}
                    hint="Tell the agent when to book (e.g. when the caller wants a meeting or a visit)."
                />
                <Field label="Calendar">
                    <Select
                        value={provider}
                        onValueChange={(v) => set({ provider: v as BookAppointmentConfig["provider"] })}
                    >
                        <SelectTrigger className="w-full sm:w-80">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="nimbora">Built-in agenda</SelectItem>
                            <SelectItem value="caldav">CalDAV — Nextcloud, iCloud, Zimbra, SOGo…</SelectItem>
                            <SelectItem value="google">Google Calendar</SelectItem>
                        </SelectContent>
                    </Select>
                </Field>
                {provider === "caldav" && (
                    <>
                        <Field label="Calendar URL" hint="The calendar collection URL (ends with the calendar name).">
                            <Input
                                placeholder="https://cloud.example.com/remote.php/dav/calendars/user/rendez-vous/"
                                value={config.calendar_url ?? ""}
                                onChange={(e) => set({ calendar_url: e.target.value || null })}
                            />
                        </Field>
                        <CredentialSelector
                            value={config.credential_uuid ?? ""}
                            onChange={(v) => set({ credential_uuid: v || null })}
                            label="CalDAV account"
                            description="A Basic Auth credential (user + app password)."
                        />
                    </>
                )}
                {provider === "google" && (
                    <>
                        <Field
                            label="Calendar ID"
                            hint="Share the calendar with the service account e-mail (“Make changes to events”)."
                        >
                            <Input
                                placeholder="rendez-vous@group.calendar.google.com"
                                value={config.calendar_id ?? ""}
                                onChange={(e) => set({ calendar_id: e.target.value || null })}
                            />
                        </Field>
                        <CredentialSelector
                            value={config.credential_uuid ?? ""}
                            onChange={(v) => set({ credential_uuid: v || null })}
                            label="Service account"
                            description="A “Google service account” credential (JSON key)."
                        />
                    </>
                )}
                <div className="grid gap-4 sm:grid-cols-4">
                    <Field label="Slot (min)">
                        <Input
                            type="number"
                            min={5}
                            value={config.slot_minutes ?? 30}
                            onChange={(e) => set({ slot_minutes: Number(e.target.value) || 30 })}
                        />
                    </Field>
                    <Field label="Buffer (min)">
                        <Input
                            type="number"
                            min={0}
                            value={config.buffer_minutes ?? 0}
                            onChange={(e) => set({ buffer_minutes: Number(e.target.value) || 0 })}
                        />
                    </Field>
                    <Field label="Notice (min)">
                        <Input
                            type="number"
                            min={0}
                            value={config.min_notice_minutes ?? 60}
                            onChange={(e) => set({ min_notice_minutes: Number(e.target.value) || 0 })}
                        />
                    </Field>
                    <Field label="Up to (days)">
                        <Input
                            type="number"
                            min={1}
                            value={config.horizon_days ?? 30}
                            onChange={(e) => set({ horizon_days: Number(e.target.value) || 30 })}
                        />
                    </Field>
                </div>
                <Field label="Opening hours" hint="Ranges separated by commas, e.g. 09:00-12:00, 14:00-18:00. Empty: closed.">
                    <div className="grid gap-2">
                        {DAYS.map((day) => (
                            <div key={day.key} className="flex items-center gap-3">
                                <span className="w-24 text-sm">{day.label}</span>
                                <Input
                                    aria-label={`Opening hours ${day.label}`}
                                    className="max-w-sm"
                                    placeholder="Fermé"
                                    defaultValue={(hours[day.key] ?? []).join(", ")}
                                    onBlur={(e) => {
                                        const next = { ...hours };
                                        const ranges = parseRanges(e.target.value);
                                        if (ranges.length) next[day.key] = ranges;
                                        else delete next[day.key];
                                        set({ opening_hours: next });
                                    }}
                                />
                            </div>
                        ))}
                    </div>
                </Field>
                <div className="flex items-center justify-between gap-4">
                    <Label htmlFor="allow-cancel">Callers can cancel their appointments</Label>
                    <Switch
                        id="allow-cancel"
                        checked={config.allow_cancel ?? true}
                        onCheckedChange={(v) => set({ allow_cancel: v })}
                    />
                </div>
                <div className="rounded-lg border border-border/60 p-3">
                    <div className="flex items-center gap-3">
                        <Button variant="outline" size="sm" onClick={testCalendar} disabled={preview?.loading}>
                            {preview?.loading && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                            Test the calendar
                        </Button>
                        <span className="text-xs text-muted-foreground">Uses the saved settings: save first.</span>
                    </div>
                    {preview && !preview.loading && (
                        <div className="mt-3 text-sm">
                            {preview.error ? (
                                <span className="text-red-400">{preview.error}</span>
                            ) : (
                                <div className="flex flex-wrap gap-2">
                                    {(preview.slots ?? []).map((s) => (
                                        <Badge key={s.label} variant="secondary">
                                            {s.label}
                                        </Badge>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}

// --------------------------------------------------------------- messages

export function SendMessageToolConfig({
    config,
    onChange,
    ...common
}: CommonProps & { config: SendMessageConfig; onChange: (config: SendMessageConfig) => void }) {
    const set = (patch: Partial<SendMessageConfig>) => onChange({ ...config, ...patch });
    const channel = config.channel ?? "sms";
    const provider = config.provider ?? "twilio";
    const setChannel = (value: SendMessageConfig["channel"]) =>
        set({
            channel: value,
            provider: value === "email" ? "smtp" : provider === "smtp" ? "twilio" : provider,
        });
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <MessageSquareText className="h-5 w-5" />
                    Message
                </CardTitle>
                <CardDescription>
                    Send the caller an SMS, a WhatsApp message or an e-mail during the call: address, payment link,
                    confirmation, tracking number… Every message is logged in Activité → Messages.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <NameAndDescription
                    {...common}
                    hint="Tell the agent what to send and when (e.g. “send the payment link once the caller agrees”)."
                />
                <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Channel">
                        <Select value={channel} onValueChange={(v) => setChannel(v as SendMessageConfig["channel"])}>
                            <SelectTrigger className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="sms">SMS</SelectItem>
                                <SelectItem value="whatsapp">WhatsApp</SelectItem>
                                <SelectItem value="email">E-mail</SelectItem>
                            </SelectContent>
                        </Select>
                    </Field>
                    {channel !== "email" && (
                        <Field label="Provider">
                            <Select
                                value={provider}
                                onValueChange={(v) => set({ provider: v as SendMessageConfig["provider"] })}
                            >
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="twilio">Twilio</SelectItem>
                                    <SelectItem value="http">Other gateway (HTTP)</SelectItem>
                                </SelectContent>
                            </Select>
                        </Field>
                    )}
                </div>
                <Field
                    label={channel === "email" ? "Sender e-mail" : "Sender"}
                    hint={
                        channel === "whatsapp"
                            ? "Your WhatsApp Business number, e.g. +14155238886. Outside the 24-hour window WhatsApp only delivers approved templates."
                            : channel === "sms"
                              ? "Your sending number or an alphanumeric sender ID (e.g. ACME)."
                              : undefined
                    }
                >
                    <Input
                        value={config.sender ?? ""}
                        placeholder={channel === "email" ? "rendez-vous@acme.fr" : "+33700000000"}
                        onChange={(e) => set({ sender: e.target.value })}
                    />
                </Field>
                {provider === "http" && channel !== "email" && (
                    <Field
                        label="Gateway URL"
                        hint="The platform POSTs JSON {to, from, message, channel} with the credential below."
                    >
                        <Input
                            placeholder="https://sms.example.com/api/send"
                            value={config.gateway_url ?? ""}
                            onChange={(e) => set({ gateway_url: e.target.value || null })}
                        />
                    </Field>
                )}
                {channel === "email" && (
                    <div className="grid gap-4 sm:grid-cols-3">
                        <Field label="SMTP server">
                            <Input
                                placeholder="smtp.acme.fr"
                                value={config.smtp_host ?? ""}
                                onChange={(e) => set({ smtp_host: e.target.value || null })}
                            />
                        </Field>
                        <Field label="Port">
                            <Input
                                type="number"
                                value={config.smtp_port ?? 587}
                                onChange={(e) => set({ smtp_port: Number(e.target.value) || 587 })}
                            />
                        </Field>
                        <Field label="Security">
                            <Select
                                value={config.smtp_security ?? "starttls"}
                                onValueChange={(v) => set({ smtp_security: v as SendMessageConfig["smtp_security"] })}
                            >
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="starttls">STARTTLS</SelectItem>
                                    <SelectItem value="ssl">SSL/TLS</SelectItem>
                                    <SelectItem value="none">None</SelectItem>
                                </SelectContent>
                            </Select>
                        </Field>
                    </div>
                )}
                <CredentialSelector
                    value={config.credential_uuid ?? ""}
                    onChange={(v) => set({ credential_uuid: v || null })}
                    label={provider === "twilio" ? "Twilio account" : channel === "email" ? "SMTP login" : "Gateway credential"}
                    description={
                        provider === "twilio"
                            ? "Basic Auth credential: Account SID as username, Auth Token as password."
                            : channel === "email"
                              ? "Basic Auth credential with the mailbox login."
                              : "Optional: API key, bearer token… sent to the gateway."
                    }
                />
                {channel === "email" && (
                    <Field label="Subject" hint="Can use {{customer_name}} and other call variables.">
                        <Input value={config.subject ?? ""} onChange={(e) => set({ subject: e.target.value || null })} />
                    </Field>
                )}
                <Field
                    label="Template (optional)"
                    hint="With a template, the agent only fills {{details}}; {{customer_name}} and extracted variables are filled in. Without one, the agent writes the message."
                >
                    <Textarea
                        rows={3}
                        placeholder="Bonjour {{customer_name}}, voici votre lien de paiement : {{details}}"
                        value={config.template ?? ""}
                        onChange={(e) => set({ template: e.target.value || null })}
                    />
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Messages per call (max)">
                        <Input
                            type="number"
                            min={1}
                            max={10}
                            value={config.max_per_call ?? 3}
                            onChange={(e) => set({ max_per_call: Number(e.target.value) || 3 })}
                        />
                    </Field>
                    {channel !== "email" && (
                        <div className="flex items-center justify-between gap-4 pt-6">
                            <Label htmlFor="other-recipient">Allow another number given by the caller</Label>
                            <Switch
                                id="other-recipient"
                                checked={config.allow_other_recipient ?? false}
                                onCheckedChange={(v) => set({ allow_other_recipient: v })}
                            />
                        </div>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}

// ---------------------------------------------------------------- tickets

export function CreateTicketToolConfig({
    config,
    onChange,
    ...common
}: CommonProps & { config: CreateTicketConfig; onChange: (config: CreateTicketConfig) => void }) {
    const set = (patch: Partial<CreateTicketConfig>) => onChange({ ...config, ...patch });
    const provider = config.provider ?? "nimbora";
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Ticket className="h-5 w-5" />
                    Ticket
                </CardTitle>
                <CardDescription>
                    Open a support ticket with the details of the call and give the caller its number. Callers can ask
                    where their tickets stand. Tickets appear in Activité → Tickets.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <NameAndDescription
                    {...common}
                    hint="Tell the agent when to open a ticket (e.g. a fault it cannot fix, a refund request)."
                />
                <Field label="Helpdesk">
                    <Select
                        value={provider}
                        onValueChange={(v) => set({ provider: v as CreateTicketConfig["provider"], domain: null })}
                    >
                        <SelectTrigger className="w-full sm:w-80">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="nimbora">Built-in tickets</SelectItem>
                            <SelectItem value="zendesk">Zendesk</SelectItem>
                            <SelectItem value="freshdesk">Freshdesk</SelectItem>
                        </SelectContent>
                    </Select>
                </Field>
                {provider !== "nimbora" && (
                    <>
                        <Field label="Domain">
                            <Input
                                placeholder={`acme.${provider}.com`}
                                value={config.domain ?? ""}
                                onChange={(e) => set({ domain: e.target.value.trim().toLowerCase() || null })}
                            />
                        </Field>
                        <CredentialSelector
                            value={config.credential_uuid ?? ""}
                            onChange={(v) => set({ credential_uuid: v || null })}
                            label={`${provider === "zendesk" ? "Zendesk" : "Freshdesk"} API access`}
                            description={
                                provider === "zendesk"
                                    ? "Basic Auth credential: “agent@acme.com/token” as username, the API token as password."
                                    : "Basic Auth credential: the API key as username, “X” as password."
                            }
                        />
                    </>
                )}
                <Field label="Categories (optional)" hint="Comma-separated; the agent picks one per ticket.">
                    <Input
                        placeholder="Facturation, Technique, Livraison"
                        defaultValue={(config.categories ?? []).join(", ")}
                        onBlur={(e) =>
                            set({
                                categories: e.target.value
                                    .split(",")
                                    .map((c) => c.trim())
                                    .filter(Boolean),
                            })
                        }
                    />
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Default priority">
                        <Select
                            value={config.default_priority ?? "normal"}
                            onValueChange={(v) => set({ default_priority: v as CreateTicketConfig["default_priority"] })}
                        >
                            <SelectTrigger className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="low">Low</SelectItem>
                                <SelectItem value="normal">Normal</SelectItem>
                                <SelectItem value="high">High</SelectItem>
                                <SelectItem value="urgent">Urgent</SelectItem>
                            </SelectContent>
                        </Select>
                    </Field>
                    <div className="flex items-center justify-between gap-4 pt-6">
                        <Label htmlFor="allow-lookup">Callers can ask about their tickets</Label>
                        <Switch
                            id="allow-lookup"
                            checked={config.allow_lookup ?? true}
                            onCheckedChange={(v) => set({ allow_lookup: v })}
                        />
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}

// ---------------------------------------------------------------- catalog

const CATALOG_KINDS: { value: NonNullable<SearchCatalogConfig["kinds"]>[number]; label: string }[] = [
    { value: "product", label: "Products" },
    { value: "property", label: "Properties" },
    { value: "room", label: "Rooms" },
    { value: "service", label: "Services" },
    { value: "vehicle", label: "Vehicles" },
    { value: "other", label: "Other" },
];

export function SearchCatalogToolConfig({
    config,
    onChange,
    ...common
}: CommonProps & { config: SearchCatalogConfig; onChange: (config: SearchCatalogConfig) => void }) {
    const set = (patch: Partial<SearchCatalogConfig>) => onChange({ ...config, ...patch });
    const kinds = config.kinds ?? [];
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Package className="h-5 w-5" />
                    Catalog
                </CardTitle>
                <CardDescription>
                    The agent searches the company&apos;s catalog (Catalogue page) with the caller&apos;s words and budget, and quotes only what it
                    finds: name, price, availability, characteristics.{" "}
                    <a className="underline" href="/catalog">
                        Open the catalog
                    </a>
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <NameAndDescription
                    {...common}
                    hint="Say what the catalog holds and when to search it (e.g. « Search our rooms and their prices when the caller asks for availability or a rate »)."
                />
                <Field label="Items the agent may offer" hint="None selected: the whole catalog.">
                    <div className="flex flex-wrap gap-2">
                        {CATALOG_KINDS.map((k) => {
                            const on = kinds.includes(k.value);
                            return (
                                <button
                                    key={k.value}
                                    type="button"
                                    aria-pressed={on}
                                    className={badgeVariants({ variant: on ? "default" : "outline" })}
                                    onClick={() => set({ kinds: on ? kinds.filter((x) => x !== k.value) : [...kinds, k.value] })}
                                >
                                    {k.label}
                                </button>
                            );
                        })}
                    </div>
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Currency of budgets" hint="« moins de 50 000 » is read in this currency.">
                        <Input className="w-32" maxLength={3} value={config.currency ?? "XOF"} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />
                    </Field>
                    <Field label="Results per search">
                        <Input
                            className="w-32"
                            type="number"
                            min={1}
                            max={10}
                            value={config.max_results ?? 5}
                            onChange={(e) => set({ max_results: Math.min(10, Math.max(1, Number(e.target.value) || 5)) })}
                        />
                    </Field>
                </div>
                <div className="flex items-center gap-3">
                    <Switch id="catalog-available" checked={config.available_only ?? true} onCheckedChange={(v) => set({ available_only: v })} />
                    <Label htmlFor="catalog-available">Leave out unavailable and sold-out items</Label>
                </div>
                <div className="flex items-center gap-3">
                    <Switch id="catalog-stock" checked={config.show_stock ?? true} onCheckedChange={(v) => set({ show_stock: v })} />
                    <Label htmlFor="catalog-stock">Tell how many are left (otherwise just « en stock »)</Label>
                </div>
            </CardContent>
        </Card>
    );
}

// ------------------------------------------------------------------ leads

export function QualifyLeadToolConfig({
    config,
    onChange,
    ...common
}: CommonProps & { config: QualifyLeadConfig; onChange: (config: QualifyLeadConfig) => void }) {
    const set = (patch: Partial<QualifyLeadConfig>) => onChange({ ...config, ...patch });
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Target className="h-5 w-5" />
                    Lead qualification
                </CardTitle>
                <CardDescription>
                    The agent records the caller&apos;s need, budget, timeline, whether they decide, and what interests them. Each answer adds to a
                    score out of 100; the tool tells the agent what is still unknown so it asks the next useful question. Leads appear in{" "}
                    <a className="underline" href="/leads">
                        Prospects
                    </a>
                    ; a caller&apos;s next call completes the same lead.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <NameAndDescription
                    {...common}
                    hint="Say when to call it (e.g. « Record the caller's project as soon as they describe it, then after each new answer »)."
                />
                <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Currency of budgets">
                        <Input className="w-32" maxLength={3} value={config.currency ?? "XOF"} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />
                    </Field>
                    <Field label="Qualified from score" hint="A new lead reaching this score moves to « Qualifié ».">
                        <Input
                            className="w-32"
                            type="number"
                            min={10}
                            max={100}
                            value={config.qualified_score ?? 60}
                            onChange={(e) => set({ qualified_score: Math.min(100, Math.max(10, Number(e.target.value) || 60)) })}
                        />
                    </Field>
                </div>
            </CardContent>
        </Card>
    );
}

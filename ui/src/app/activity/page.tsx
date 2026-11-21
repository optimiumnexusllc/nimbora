"use client";

import { CalendarCheck, ExternalLink, MessageSquareText, Ticket, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    cancelAppointmentApiV1ActionsAppointmentsAppointmentIdCancelPost,
    listAppointmentsApiV1ActionsAppointmentsGet,
    listMessagesApiV1ActionsMessagesGet,
    listTicketsApiV1ActionsTicketsGet,
    summaryApiV1ActionsSummaryGet,
    updateTicketApiV1ActionsTicketsTicketIdPatch,
} from "@/client/sdk.gen";
import type {
    ActivitySummary,
    AppointmentResponse,
    SentMessageResponse,
    TicketResponse,
} from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

const PRIORITY: Record<string, { label: string; className: string }> = {
    low: { label: "Basse", className: "bg-muted text-muted-foreground" },
    normal: { label: "Normale", className: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" },
    high: { label: "Haute", className: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
    urgent: { label: "Urgente", className: "bg-red-500/15 text-red-300 border-red-500/30" },
};
const STATUS: Record<string, string> = {
    open: "Ouvert",
    pending: "En attente",
    solved: "Résolu",
    closed: "Clôturé",
};
const CHANNEL: Record<string, string> = { sms: "SMS", whatsapp: "WhatsApp", email: "E-mail" };

function dayLabel(iso: string) {
    const label = new Date(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
    return label.charAt(0).toUpperCase() + label.slice(1);
}

function time(iso: string) {
    return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function Appointments() {
    const [view, setView] = useState<"upcoming" | "past">("upcoming");
    const [rows, setRows] = useState<AppointmentResponse[] | null>(null);

    const load = useCallback(async () => {
        const response = await listAppointmentsApiV1ActionsAppointmentsGet({ query: { view } });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Chargement impossible"));
            setRows([]);
            return;
        }
        setRows(response.data);
    }, [view]);

    useEffect(() => {
        void load();
    }, [load]);

    const cancel = async (row: AppointmentResponse) => {
        if (!window.confirm(`Annuler le rendez-vous de ${row.customer_name || row.phone || "ce client"} ?`)) return;
        const response = await cancelAppointmentApiV1ActionsAppointmentsAppointmentIdCancelPost({
            path: { appointment_id: row.id },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Annulation impossible"));
            return;
        }
        toast.success("Rendez-vous annulé");
        void load();
    };

    const groups = new Map<string, AppointmentResponse[]>();
    for (const row of rows ?? []) {
        const key = dayLabel(row.start_at);
        groups.set(key, [...(groups.get(key) ?? []), row]);
    }

    return (
        <div className="space-y-4">
            <Tabs value={view} onValueChange={(v) => setView(v as "upcoming" | "past")}>
                <TabsList>
                    <TabsTrigger value="upcoming">À venir</TabsTrigger>
                    <TabsTrigger value="past">Passés</TabsTrigger>
                </TabsList>
            </Tabs>
            {rows !== null && rows.length === 0 && (
                <p className="text-sm text-muted-foreground">
                    Aucun rendez-vous. Ajoutez l&apos;outil « Book Appointment » à un agent pour qu&apos;il prenne des
                    rendez-vous pendant les appels.
                </p>
            )}
            {[...groups.entries()].map(([day, items]) => (
                <div key={day}>
                    <h3 className="mb-2 text-sm font-medium text-muted-foreground">{day}</h3>
                    <div className="grid gap-2">
                        {items.map((row) => (
                            <div
                                key={row.id}
                                data-testid="appointment-row"
                                className={`flex flex-wrap items-center gap-4 rounded-xl border border-border/60 bg-card/40 px-4 py-3 ${
                                    row.status === "canceled" ? "opacity-50" : ""
                                }`}
                            >
                                <div className="w-28 font-mono text-sm tabular-nums">
                                    {time(row.start_at)} – {time(row.end_at)}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="font-medium">{row.customer_name || row.phone || "Client"}</div>
                                    <div className="truncate text-xs text-muted-foreground">
                                        {[row.reason, row.phone, row.email].filter(Boolean).join(" · ")}
                                    </div>
                                </div>
                                <Badge variant="outline">{row.calendar_name || "Agenda"}</Badge>
                                {row.status === "canceled" ? (
                                    <Badge variant="secondary">Annulé</Badge>
                                ) : (
                                    view === "upcoming" && (
                                        <Button variant="ghost" size="sm" onClick={() => cancel(row)}>
                                            <X className="mr-1 h-4 w-4" />
                                            Annuler
                                        </Button>
                                    )
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}

function Messages() {
    const [rows, setRows] = useState<SentMessageResponse[] | null>(null);
    useEffect(() => {
        void (async () => {
            const response = await listMessagesApiV1ActionsMessagesGet();
            setRows(response.error || !response.data ? [] : response.data);
        })();
    }, []);
    if (rows === null) return null;
    if (rows.length === 0) {
        return (
            <p className="text-sm text-muted-foreground">
                Aucun message envoyé. L&apos;outil « Send Message » permet aux agents d&apos;envoyer un SMS, un WhatsApp ou
                un e-mail pendant l&apos;appel.
            </p>
        );
    }
    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Canal</TableHead>
                    <TableHead>Destinataire</TableHead>
                    <TableHead>Message</TableHead>
                    <TableHead>Statut</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {rows.map((m) => (
                    <TableRow key={m.id}>
                        <TableCell className="whitespace-nowrap text-sm">
                            {m.created_at ? new Date(m.created_at).toLocaleString("fr-FR") : ""}
                        </TableCell>
                        <TableCell>
                            <Badge variant="outline">{CHANNEL[m.channel] ?? m.channel}</Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{m.recipient}</TableCell>
                        <TableCell className="max-w-md text-sm">
                            {m.subject && <div className="font-medium">{m.subject}</div>}
                            <div className="line-clamp-2 text-muted-foreground">{m.body}</div>
                        </TableCell>
                        <TableCell>
                            {m.status === "sent" ? (
                                <Badge>Envoyé</Badge>
                            ) : (
                                <Badge variant="destructive" title={m.error ?? undefined}>
                                    Échec
                                </Badge>
                            )}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}

function Tickets() {
    const [view, setView] = useState<"open" | "closed" | "all">("open");
    const [rows, setRows] = useState<TicketResponse[] | null>(null);
    const [selected, setSelected] = useState<TicketResponse | null>(null);
    const [resolution, setResolution] = useState("");

    const load = useCallback(async () => {
        const response = await listTicketsApiV1ActionsTicketsGet({ query: { view } });
        setRows(response.error || !response.data ? [] : response.data);
    }, [view]);
    useEffect(() => {
        void load();
    }, [load]);

    const update = async (ticket: TicketResponse, body: Record<string, unknown>) => {
        const response = await updateTicketApiV1ActionsTicketsTicketIdPatch({
            path: { ticket_id: ticket.id },
            body,
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Mise à jour impossible"));
            return;
        }
        setSelected(response.data);
        toast.success("Ticket mis à jour");
        void load();
    };

    return (
        <div className="space-y-4">
            <Tabs value={view} onValueChange={(v) => setView(v as typeof view)}>
                <TabsList>
                    <TabsTrigger value="open">À traiter</TabsTrigger>
                    <TabsTrigger value="closed">Résolus</TabsTrigger>
                    <TabsTrigger value="all">Tous</TabsTrigger>
                </TabsList>
            </Tabs>
            {rows !== null && rows.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                    Aucun ticket. L&apos;outil « Create Ticket » permet aux agents d&apos;ouvrir un ticket et d&apos;en donner
                    le numéro à l&apos;appelant.
                </p>
            ) : (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>N°</TableHead>
                            <TableHead>Objet</TableHead>
                            <TableHead>Client</TableHead>
                            <TableHead>Priorité</TableHead>
                            <TableHead>Statut</TableHead>
                            <TableHead>Ouvert le</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {(rows ?? []).map((t) => (
                            <TableRow
                                key={t.id}
                                data-testid="ticket-row"
                                className="cursor-pointer"
                                onClick={() => {
                                    setSelected(t);
                                    setResolution(t.resolution ?? "");
                                }}
                            >
                                <TableCell className="font-mono">#{t.number}</TableCell>
                                <TableCell className="font-medium">
                                    {t.subject}
                                    {t.category && (
                                        <Badge variant="outline" className="ml-2">
                                            {t.category}
                                        </Badge>
                                    )}
                                </TableCell>
                                <TableCell className="text-sm">{t.customer_name || t.phone || "—"}</TableCell>
                                <TableCell>
                                    <Badge variant="outline" className={PRIORITY[t.priority]?.className}>
                                        {PRIORITY[t.priority]?.label ?? t.priority}
                                    </Badge>
                                </TableCell>
                                <TableCell>{STATUS[t.status] ?? t.status}</TableCell>
                                <TableCell className="whitespace-nowrap text-sm">
                                    {t.created_at ? new Date(t.created_at).toLocaleDateString("fr-FR") : ""}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}

            <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
                <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
                    {selected && (
                        <>
                            <SheetHeader>
                                <SheetTitle>
                                    #{selected.number} — {selected.subject}
                                </SheetTitle>
                                <SheetDescription>
                                    {selected.customer_name || "Client"} · {selected.phone || "numéro inconnu"}
                                    {selected.email ? ` · ${selected.email}` : ""}
                                </SheetDescription>
                            </SheetHeader>
                            <div className="space-y-5 p-4">
                                <p className="whitespace-pre-wrap text-sm">{selected.description}</p>
                                {selected.external_url && (
                                    <a
                                        href={selected.external_url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="inline-flex items-center gap-1 text-sm text-primary"
                                    >
                                        Ouvrir dans {selected.provider === "zendesk" ? "Zendesk" : "Freshdesk"}
                                        <ExternalLink className="h-3.5 w-3.5" />
                                    </a>
                                )}
                                <div className="grid grid-cols-2 gap-3">
                                    <Select
                                        value={selected.status}
                                        onValueChange={(v) => update(selected, { status: v })}
                                    >
                                        <SelectTrigger className="w-full" aria-label="Statut">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {Object.entries(STATUS).map(([value, label]) => (
                                                <SelectItem key={value} value={value}>
                                                    {label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        value={selected.priority}
                                        onValueChange={(v) => update(selected, { priority: v })}
                                    >
                                        <SelectTrigger className="w-full" aria-label="Priorité">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {Object.entries(PRIORITY).map(([value, { label }]) => (
                                                <SelectItem key={value} value={value}>
                                                    {label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <p className="text-sm font-medium">Résolution</p>
                                    <p className="text-xs text-muted-foreground">
                                        Lue au client par l&apos;agent IA quand il demande où en est son ticket.
                                    </p>
                                    <Textarea
                                        rows={3}
                                        value={resolution}
                                        onChange={(e) => setResolution(e.target.value)}
                                    />
                                    <div className="flex gap-2">
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => update(selected, { resolution })}
                                        >
                                            Enregistrer
                                        </Button>
                                        <Button
                                            size="sm"
                                            onClick={() => update(selected, { resolution, status: "solved" })}
                                        >
                                            Marquer résolu
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </SheetContent>
            </Sheet>
        </div>
    );
}

export default function ActivityPage() {
    const { user, loading: authLoading } = useAuth();
    const [summary, setSummary] = useState<ActivitySummary | null>(null);
    const started = useRef(false);

    useEffect(() => {
        if (authLoading || !user || started.current) return;
        started.current = true;
        void (async () => {
            const response = await summaryApiV1ActionsSummaryGet();
            setSummary(response.error || !response.data ? { upcoming_appointments: 0, messages_today: 0, open_tickets: 0 } : response.data);
        })();
    }, [authLoading, user]);

    if (!summary) {
        return <PageLayout title="Activité">{null}</PageLayout>;
    }

    return (
        <PageLayout
            title="Activité"
            description="Ce que vos agents IA ont fait pendant les appels : rendez-vous pris, messages envoyés, tickets ouverts."
        >
            <PageSection title="Actions des agents">
                <Tabs defaultValue="appointments">
                    <TabsList className="mb-4">
                        <TabsTrigger value="appointments">
                            <CalendarCheck className="mr-1.5 h-4 w-4" />
                            Rendez-vous
                            <Badge variant="secondary" className="ml-2">
                                {summary.upcoming_appointments}
                            </Badge>
                        </TabsTrigger>
                        <TabsTrigger value="messages">
                            <MessageSquareText className="mr-1.5 h-4 w-4" />
                            Messages
                            <Badge variant="secondary" className="ml-2">
                                {summary.messages_today}
                            </Badge>
                        </TabsTrigger>
                        <TabsTrigger value="tickets">
                            <Ticket className="mr-1.5 h-4 w-4" />
                            Tickets
                            <Badge variant="secondary" className="ml-2">
                                {summary.open_tickets}
                            </Badge>
                        </TabsTrigger>
                    </TabsList>
                    <TabsContent value="appointments">
                        <Appointments />
                    </TabsContent>
                    <TabsContent value="messages">
                        <Messages />
                    </TabsContent>
                    <TabsContent value="tickets">
                        <Tickets />
                    </TabsContent>
                </Tabs>
            </PageSection>
        </PageLayout>
    );
}

"use client";

import { Bot, ExternalLink, MessageCircle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
    getConversationApiV1WhatsappConversationsConversationIdGet,
    listConversationsApiV1WhatsappConversationsGet,
} from "@/client/sdk.gen";
import type { ConversationDetail, ConversationResponse } from "@/client/types.gen";
import { PageLayout } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

type StatusFilter = "all" | "open" | "closed";

const REFRESH_MS = 10_000;

function when(iso: string | null | undefined): string {
    if (!iso) return "";
    const date = new Date(iso);
    const sameDay = date.toDateString() === new Date().toDateString();
    return date.toLocaleString("fr-FR", sameDay ? { timeStyle: "short" } : { dateStyle: "short", timeStyle: "short" });
}

function displayNumber(waId: string): string {
    return waId.startsWith("+") ? waId : `+${waId}`;
}

function Transcript({ conversation }: { conversation: ConversationDetail }) {
    const end = useRef<HTMLDivElement>(null);
    useEffect(() => {
        end.current?.scrollIntoView?.({ block: "end" });
    }, [conversation.messages.length]);

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-5 py-3">
                <div className="flex size-9 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                    <MessageCircle className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{conversation.customer_name || displayNumber(conversation.customer_wa_id)}</p>
                    <p className="font-mono text-xs text-muted-foreground">
                        {displayNumber(conversation.customer_wa_id)}
                        {conversation.business_number ? ` → ${conversation.business_number}` : ""}
                    </p>
                </div>
                <Badge variant={conversation.status === "open" ? "default" : "secondary"}>
                    {conversation.status === "open" ? "En cours" : "Terminée"}
                </Badge>
                {conversation.workflow_id && conversation.workflow_run_id ? (
                    <Button asChild size="sm" variant="ghost">
                        <Link href={`/workflow/${conversation.workflow_id}/run/${conversation.workflow_run_id}`}>
                            <ExternalLink /> Exécution
                        </Link>
                    </Button>
                ) : null}
            </div>
            <div
                className="min-h-0 flex-1 space-y-2 overflow-y-auto bg-[radial-gradient(circle_at_1px_1px,hsl(var(--border)/0.5)_1px,transparent_0)] bg-[length:18px_18px] px-5 py-4"
                data-testid="transcript"
            >
                {conversation.messages.length === 0 ? (
                    <p className="py-10 text-center text-sm text-muted-foreground">Aucun message pour l&apos;instant.</p>
                ) : (
                    conversation.messages.map((message, index) => (
                        <div
                            key={index}
                            className={cn("flex", message.role === "customer" ? "justify-start" : "justify-end")}
                        >
                            <div
                                className={cn(
                                    "max-w-[78%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm shadow-sm",
                                    message.role === "customer"
                                        ? "rounded-tl-sm bg-card"
                                        : "rounded-tr-sm bg-emerald-600/90 text-white",
                                )}
                            >
                                {message.role === "agent" && (
                                    <span className="mb-0.5 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-white/70">
                                        <Bot className="size-3" /> Agent IA
                                    </span>
                                )}
                                {message.text}
                                {message.at && (
                                    <span className="mt-0.5 block text-right text-[10px] opacity-60">{when(message.at)}</span>
                                )}
                            </div>
                        </div>
                    ))
                )}
                <div ref={end} />
            </div>
        </div>
    );
}

export default function ConversationsPage() {
    const { user, loading: authLoading } = useAuth();
    const [status, setStatus] = useState<StatusFilter>("all");
    const [conversations, setConversations] = useState<ConversationResponse[] | null>(null);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [detail, setDetail] = useState<ConversationDetail | null>(null);
    const [error, setError] = useState<string | null>(null);

    const loadList = useCallback(async (filter: StatusFilter) => {
        const response = await listConversationsApiV1WhatsappConversationsGet({ query: { status: filter } });
        if (response.error) {
            setError(detailFromError(response.error, "Impossible de charger les conversations"));
            return;
        }
        setError(null);
        const rows = response.data ?? [];
        setConversations(rows);
        setSelectedId((current) => current ?? rows[0]?.id ?? null);
    }, []);

    const loadDetail = useCallback(async (id: number) => {
        const response = await getConversationApiV1WhatsappConversationsConversationIdGet({
            path: { conversation_id: id },
        });
        if (response.error) {
            setError(detailFromError(response.error, "Impossible de charger la conversation"));
            return;
        }
        setDetail(response.data ?? null);
    }, []);

    useEffect(() => {
        if (authLoading || !user) return;
        void loadList(status);
        const timer = setInterval(() => void loadList(status), REFRESH_MS);
        return () => clearInterval(timer);
    }, [authLoading, user, status, loadList]);

    useEffect(() => {
        if (authLoading || !user || selectedId === null) return;
        void loadDetail(selectedId);
        const timer = setInterval(() => void loadDetail(selectedId), REFRESH_MS);
        return () => clearInterval(timer);
    }, [authLoading, user, selectedId, loadDetail]);

    const openCount = conversations?.filter((c) => c.status === "open").length ?? 0;

    return (
        <PageLayout
            title="Conversations"
            description="Les échanges WhatsApp menés par vos agents IA. Ils partagent la mémoire client avec les appels et le chat web."
            actions={
                <Button
                    variant="outline"
                    onClick={() => {
                        void loadList(status);
                        if (selectedId !== null) void loadDetail(selectedId);
                    }}
                >
                    <RefreshCw /> Actualiser
                </Button>
            }
        >
            {error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">{error}</p>}
            <div className="grid min-h-[560px] overflow-hidden rounded-xl border border-border/60 md:grid-cols-[320px_1fr]">
                <aside className="flex min-h-0 flex-col border-b border-border/60 md:border-b-0 md:border-r">
                    <div className="border-b border-border/60 p-3">
                        <Tabs value={status} onValueChange={(v) => setStatus(v as StatusFilter)}>
                            <TabsList className="w-full">
                                <TabsTrigger value="all">Toutes</TabsTrigger>
                                <TabsTrigger value="open">En cours{status === "all" && openCount ? ` (${openCount})` : ""}</TabsTrigger>
                                <TabsTrigger value="closed">Terminées</TabsTrigger>
                            </TabsList>
                        </Tabs>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        {conversations === null ? (
                            <div className="space-y-2 p-3">
                                <Skeleton className="h-14" />
                                <Skeleton className="h-14" />
                            </div>
                        ) : conversations.length === 0 ? (
                            <div className="space-y-2 p-6 text-center text-sm text-muted-foreground">
                                <MessageCircle className="mx-auto size-8 opacity-50" />
                                <p>Aucune conversation WhatsApp.</p>
                                <p className="text-xs">
                                    Associez un agent à votre numéro WhatsApp Business dans{" "}
                                    <Link href="/telephony-configurations" className="underline">
                                        Téléphonie
                                    </Link>{" "}
                                    : il répondra automatiquement aux messages.
                                </p>
                            </div>
                        ) : (
                            <ul>
                                {conversations.map((c) => (
                                    <li key={c.id}>
                                        <button
                                            type="button"
                                            data-testid="conversation-row"
                                            onClick={() => setSelectedId(c.id)}
                                            className={cn(
                                                "flex w-full items-start gap-3 border-b border-border/40 px-4 py-3 text-left transition-colors hover:bg-muted/40",
                                                selectedId === c.id && "bg-muted/60",
                                            )}
                                        >
                                            <span
                                                className={cn(
                                                    "mt-1.5 size-2 shrink-0 rounded-full",
                                                    c.status === "open" ? "bg-emerald-400" : "bg-muted-foreground/40",
                                                )}
                                            />
                                            <span className="min-w-0 flex-1">
                                                <span className="flex items-baseline justify-between gap-2">
                                                    <span className="truncate font-medium">
                                                        {c.customer_name || displayNumber(c.customer_wa_id)}
                                                    </span>
                                                    <span className="shrink-0 text-xs text-muted-foreground">
                                                        {when(c.last_inbound_at ?? c.created_at)}
                                                    </span>
                                                </span>
                                                <span className="block text-xs text-muted-foreground">
                                                    {displayNumber(c.customer_wa_id)} · {c.message_count} message
                                                    {c.message_count > 1 ? "s" : ""}
                                                </span>
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </aside>
                <section className="min-h-0">
                    {detail && detail.id === selectedId ? (
                        <Transcript conversation={detail} />
                    ) : selectedId !== null ? (
                        <Skeleton className="m-5 h-64" />
                    ) : (
                        <div className="flex h-full items-center justify-center p-10 text-sm text-muted-foreground">
                            Sélectionnez une conversation.
                        </div>
                    )}
                </section>
            </div>
        </PageLayout>
    );
}

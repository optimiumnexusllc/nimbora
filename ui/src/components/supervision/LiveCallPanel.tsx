"use client";

import { Bot, Headset, Megaphone, PhoneOff, Send, User, Wrench } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    callActionApiV1SupervisionCallsRunIdActionsPost,
    callEventsApiV1SupervisionCallsRunIdEventsGet,
} from "@/client/sdk.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

export type LiveEvent = {
    seq: number;
    kind: string;
    text?: string | null;
    name?: string | null;
    action?: string | null;
    status?: string | null;
    error?: string | null;
    by?: string | null;
    at: number;
};

export type FeedItem =
    | { type: "caller" | "agent"; text: string; at: number; key: string }
    | { type: "note"; text: string; tone: "tool" | "supervisor" | "error" | "info"; at: number; key: string };

const ACTION_LABELS: Record<string, string> = {
    instruct: "Consigne soufflée à l'IA",
    say: "Phrase dite par l'agent",
    takeover: "Transfert vers un conseiller",
    hangup: "Appel raccroché par le superviseur",
};

/** Merge chunked agent text into bubbles and turn events into feed items. */
export function buildFeed(events: LiveEvent[]): FeedItem[] {
    const items: FeedItem[] = [];
    for (const event of events) {
        const key = String(event.seq);
        const last = items[items.length - 1];
        if (event.kind === "caller" && event.text) {
            items.push({ type: "caller", text: event.text, at: event.at, key });
        } else if (event.kind === "agent" && event.text) {
            if (last && last.type === "agent") last.text = `${last.text} ${event.text}`.replace(/\s+/g, " ").trim();
            else items.push({ type: "agent", text: event.text, at: event.at, key });
        } else if (event.kind === "tool" && event.name) {
            items.push({ type: "note", tone: "tool", text: `Outil : ${event.name}`, at: event.at, key });
        } else if (event.kind === "node" && event.name) {
            items.push({ type: "note", tone: "info", text: `Étape : ${event.name}`, at: event.at, key });
        } else if (event.kind === "supervisor") {
            const label = ACTION_LABELS[event.action ?? ""] ?? "Action du superviseur";
            const detail = event.text ? ` — « ${event.text} »` : "";
            const failed = event.status !== "ok" ? ` (échec${event.error ? ` : ${event.error}` : ""})` : "";
            items.push({ type: "note", tone: "supervisor", text: `${label}${detail}${failed}`, at: event.at, key });
        } else if (event.kind === "error" && event.text) {
            items.push({ type: "note", tone: "error", text: event.text, at: event.at, key });
        } else if (event.kind === "ended") {
            items.push({ type: "note", tone: "info", text: "Appel terminé", at: event.at, key });
        }
    }
    return items;
}

export interface LiveCallSummary {
    run_id: number;
    agent_name?: string;
    caller?: string;
    direction?: string;
    language?: string;
}

export function LiveCallPanel({
    call,
    queues,
    onClose,
}: {
    call: LiveCallSummary | null;
    queues: { slug: string; name: string }[];
    onClose: () => void;
}) {
    const [events, setEvents] = useState<LiveEvent[]>([]);
    const [live, setLive] = useState(true);
    const [text, setText] = useState("");
    const [queue, setQueue] = useState("");
    const [sending, setSending] = useState<string | null>(null);
    const lastSeq = useRef(0);
    const bottom = useRef<HTMLDivElement>(null);
    const runId = call?.run_id;

    useEffect(() => {
        setEvents([]);
        setLive(true);
        setText("");
        lastSeq.current = 0;
    }, [runId]);

    const poll = useCallback(async () => {
        if (!runId) return;
        const response = await callEventsApiV1SupervisionCallsRunIdEventsGet({
            path: { run_id: runId },
            query: { after: lastSeq.current },
        });
        if (response.error || !response.data) return;
        const data = response.data as { events: LiveEvent[]; live: boolean };
        if (data.events.length) {
            lastSeq.current = Math.max(...data.events.map((e) => e.seq));
            setEvents((previous) => [...previous, ...data.events]);
        }
        setLive(data.live);
    }, [runId]);

    useEffect(() => {
        if (!runId) return;
        void poll();
        const timer = window.setInterval(() => void poll(), 1200);
        return () => window.clearInterval(timer);
    }, [runId, poll]);

    useEffect(() => {
        bottom.current?.scrollIntoView?.({ block: "end" });
    }, [events.length]);

    const act = async (action: "instruct" | "say" | "takeover" | "hangup") => {
        if (!runId) return;
        setSending(action);
        const response = await callActionApiV1SupervisionCallsRunIdActionsPost({
            path: { run_id: runId },
            body: {
                action,
                text: text.trim() || null,
                queue_slug: action === "takeover" ? queue : null,
            },
        });
        setSending(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Action impossible"));
            return;
        }
        if (action === "instruct" || action === "say") setText("");
        toast.success(
            action === "instruct"
                ? "Consigne transmise à l'agent IA"
                : action === "say"
                  ? "L'agent va le dire"
                  : action === "takeover"
                    ? "Transfert en cours"
                    : "Fin d'appel demandée",
        );
    };

    const feed = buildFeed(events);

    return (
        <Sheet open={call !== null} onOpenChange={(open) => !open && onClose()}>
            <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
                <SheetHeader className="border-b border-border/60 p-5">
                    <SheetTitle className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full ${live ? "animate-pulse bg-emerald-400" : "bg-muted-foreground"}`} />
                        {call?.agent_name ?? "Appel IA"}
                        {call?.language && <Badge variant="outline">{call.language.toUpperCase()}</Badge>}
                    </SheetTitle>
                    <SheetDescription>
                        {call?.direction === "outbound" ? "Vers" : "De"} {call?.caller || "numéro masqué"} ·{" "}
                        {live ? "en direct" : "terminé"}
                    </SheetDescription>
                </SheetHeader>

                <div className="flex-1 space-y-3 overflow-y-auto p-5" data-testid="live-feed">
                    {feed.length === 0 && (
                        <p className="text-sm text-muted-foreground">En attente des premières paroles…</p>
                    )}
                    {feed.map((item) =>
                        item.type === "note" ? (
                            <div
                                key={item.key}
                                className={`flex items-center justify-center gap-1.5 text-center text-xs ${
                                    item.tone === "supervisor"
                                        ? "text-cyan-300"
                                        : item.tone === "error"
                                          ? "text-red-400"
                                          : "text-muted-foreground"
                                }`}
                            >
                                {item.tone === "tool" && <Wrench className="h-3 w-3" />}
                                {item.tone === "supervisor" && <Headset className="h-3 w-3" />}
                                {item.text}
                            </div>
                        ) : (
                            <div
                                key={item.key}
                                className={`flex gap-2 ${item.type === "agent" ? "flex-row-reverse text-right" : ""}`}
                            >
                                <div
                                    className={`mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                                        item.type === "agent" ? "bg-violet-500/20 text-violet-300" : "bg-cyan-500/20 text-cyan-300"
                                    }`}
                                >
                                    {item.type === "agent" ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
                                </div>
                                <p
                                    className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${
                                        item.type === "agent" ? "bg-violet-500/10" : "bg-card/70"
                                    }`}
                                >
                                    {item.text}
                                </p>
                            </div>
                        ),
                    )}
                    <div ref={bottom} />
                </div>

                <div className="space-y-3 border-t border-border/60 p-5">
                    <Textarea
                        rows={2}
                        placeholder="Ex. : propose-lui un geste commercial de 10 %"
                        value={text}
                        disabled={!live}
                        onChange={(e) => setText(e.target.value)}
                    />
                    <div className="flex flex-wrap gap-2">
                        <Button size="sm" disabled={!live || !text.trim() || sending !== null} onClick={() => act("instruct")}>
                            <Send className="mr-1 h-4 w-4" />
                            Souffler à l&apos;IA
                        </Button>
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={!live || !text.trim() || sending !== null}
                            onClick={() => act("say")}
                        >
                            <Megaphone className="mr-1 h-4 w-4" />
                            Faire dire
                        </Button>
                        <Button
                            size="sm"
                            variant="ghost"
                            className="ml-auto text-red-400 hover:text-red-300"
                            disabled={!live || sending !== null}
                            onClick={() => act("hangup")}
                        >
                            <PhoneOff className="mr-1 h-4 w-4" />
                            Raccrocher
                        </Button>
                    </div>
                    {queues.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                            <Select value={queue} onValueChange={setQueue}>
                                <SelectTrigger className="h-8 w-56">
                                    <SelectValue placeholder="Reprendre : choisir une file" />
                                </SelectTrigger>
                                <SelectContent>
                                    {queues.map((q) => (
                                        <SelectItem key={q.slug} value={q.slug}>
                                            {q.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                size="sm"
                                variant="outline"
                                disabled={!live || !queue || sending !== null}
                                onClick={() => act("takeover")}
                            >
                                <Headset className="mr-1 h-4 w-4" />
                                Transférer à un conseiller
                            </Button>
                        </div>
                    )}
                    <p className="text-xs text-muted-foreground">
                        « Souffler » guide l&apos;IA sans que le client l&apos;entende ; « Faire dire » lui fait prononcer
                        votre phrase. Le texte saisi accompagne aussi un transfert ou une fin d&apos;appel.
                    </p>
                </div>
            </SheetContent>
        </Sheet>
    );
}

"use client";

import { CheckCircle2, Wrench, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { readAgentTestRunApiV1AgentTestsRunsRunIdGet } from "@/client/sdk.gen";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { durationText, isPending, type RunDetail, type RunResult, STATUS_LABELS } from "@/lib/agentTests";
import { cn } from "@/lib/utils";

function Verdict({ passed, children }: { passed: boolean; children: React.ReactNode }) {
    return (
        <li className="flex gap-2 text-sm">
            {passed ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-label="réussi" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="échoué" />}
            <div>{children}</div>
        </li>
    );
}

/** One run: verdict, criteria, checks, the conversation and the tools used. */
export function RunSheet({ runId, testName, onClose }: { runId: number | null; testName: string; onClose: () => void }) {
    const [run, setRun] = useState<RunDetail | null>(null);

    useEffect(() => {
        setRun(null);
        if (runId === null) return;
        let stop = false;
        const load = async () => {
            const response = await readAgentTestRunApiV1AgentTestsRunsRunIdGet({ path: { run_id: runId } });
            if (stop || !response.data) return;
            const data = response.data as unknown as RunDetail;
            setRun(data);
            if (isPending(data.status)) setTimeout(load, 3000);
        };
        void load();
        return () => {
            stop = true;
        };
    }, [runId]);

    const result = run && "transcript" in run.result ? (run.result as RunResult) : null;
    return (
        <Sheet open={runId !== null} onOpenChange={(v) => !v && onClose()}>
            <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
                <SheetHeader>
                    <SheetTitle>{testName}</SheetTitle>
                    <SheetDescription>
                        {run ? (
                            <>
                                <Badge variant={run.status === "passed" ? "secondary" : "outline"} data-testid="run-status">
                                    {STATUS_LABELS[run.status]}
                                </Badge>{" "}
                                {run.version === "published" ? "Version publiée" : "Brouillon"}
                                {result && ` · ${result.outcome_label} · ${result.metrics.turns} répliques · ${durationText(result.metrics.elapsed_ms)}`}
                            </>
                        ) : (
                            "Chargement…"
                        )}
                    </SheetDescription>
                </SheetHeader>
                {run && (
                    <div className="space-y-5 px-4 pb-6">
                        {run.error && <p className="text-sm text-destructive">{run.error}</p>}
                        {isPending(run.status) && <p className="text-sm text-muted-foreground">Le client simulé et l&apos;agent échangent… (actualisé toutes les 3 s)</p>}
                        {result?.summary && <p className="rounded-md bg-muted/40 p-3 text-sm">{result.summary}</p>}
                        {result && (result.criteria.length > 0 || result.checks.length > 0 || result.failures.length > 0) && (
                            <section className="space-y-2">
                                <h3 className="text-sm font-medium">Résultat</h3>
                                <ul className="space-y-2" data-testid="verdicts">
                                    {result.criteria.map((c) => (
                                        <Verdict key={c.criterion} passed={c.passed}>
                                            <p>{c.criterion}</p>
                                            <p className="text-xs text-muted-foreground">{c.reason}</p>
                                        </Verdict>
                                    ))}
                                    {result.checks.map((c) => (
                                        <Verdict key={c.check} passed={c.passed}>
                                            {c.check}
                                        </Verdict>
                                    ))}
                                    {result.failures.map((f) => (
                                        <Verdict key={f} passed={false}>
                                            {f}
                                        </Verdict>
                                    ))}
                                </ul>
                            </section>
                        )}
                        {result && (
                            <section className="space-y-2">
                                <h3 className="text-sm font-medium">Conversation</h3>
                                <ol className="space-y-2" data-testid="transcript">
                                    {result.transcript.map((t, i) => (
                                        <li key={i} className={cn("max-w-[85%] rounded-lg px-3 py-2 text-sm", t.role === "agent" ? "bg-muted/50" : "ml-auto border")}>
                                            <span className="block text-xs text-muted-foreground">{t.role === "agent" ? `Agent${t.node ? ` · ${t.node}` : ""}` : "Client simulé"}</span>
                                            {t.text}
                                        </li>
                                    ))}
                                </ol>
                            </section>
                        )}
                        {result && result.tool_calls.length > 0 && (
                            <section className="space-y-2">
                                <h3 className="text-sm font-medium">Outils utilisés</h3>
                                <ul className="space-y-1 text-xs">
                                    {result.tool_calls.map((c, i) => (
                                        <li key={i} className="flex gap-2">
                                            <Wrench className="size-3.5 shrink-0" aria-hidden />
                                            <code className="break-all">
                                                {c.name}({JSON.stringify(c.arguments)})
                                            </code>
                                            <span className="shrink-0 text-muted-foreground">{c.live ? "lu sur vos données" : "simulé"}</span>
                                        </li>
                                    ))}
                                </ul>
                            </section>
                        )}
                        {result && (
                            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                                {result.notes.map((n) => (
                                    <li key={n}>{n}</li>
                                ))}
                                <li>La voix (délais, interruptions) n&apos;est pas testée : seul le texte l&apos;est.</li>
                            </ul>
                        )}
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

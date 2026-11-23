"use client";

import { ArrowLeft, FlaskConical, Loader2, Pencil, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    createAgentTestApiV1AgentTestsPost,
    deleteAgentTestApiV1AgentTestsTestIdDelete,
    listAgentTestsApiV1AgentTestsGet,
    runAgentTestsApiV1AgentTestsRunPost,
    suggestAgentTestsApiV1AgentTestsSuggestPost,
    updateAgentTestApiV1AgentTestsTestIdPut,
} from "@/client/sdk.gen";
import { RunSheet } from "@/components/agent-tests/RunSheet";
import { TestEditor } from "@/components/agent-tests/TestEditor";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type AgentTest, type AgentTestInput, EMPTY_TEST, isPending, STATUS_LABELS } from "@/lib/agentTests";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

export default function AgentTestsPage() {
    const { workflowId } = useParams();
    const workflow_id = Number(workflowId);
    const { user, loading } = useAuth();
    const [tests, setTests] = useState<AgentTest[] | null>(null);
    const [version, setVersion] = useState<"draft" | "published">("draft");
    const [editing, setEditing] = useState<{ id: number | null; value: AgentTestInput } | null>(null);
    const [saving, setSaving] = useState(false);
    const [running, setRunning] = useState(false);
    const [suggesting, setSuggesting] = useState(false);
    const [suggestions, setSuggestions] = useState<AgentTestInput[] | null>(null);
    const [openRun, setOpenRun] = useState<{ id: number; name: string } | null>(null);

    const load = useCallback(async () => {
        const response = await listAgentTestsApiV1AgentTestsGet({ query: { workflow_id } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Tests indisponibles"));
            return;
        }
        setTests(response.data as unknown as AgentTest[]);
    }, [workflow_id]);

    useEffect(() => {
        if (loading || !user) return;
        void load();
    }, [loading, user, load]);

    // Runs are background jobs: refresh while one is queued or running.
    const pending = tests?.some((t) => isPending(t.last_run?.status));
    useEffect(() => {
        if (!pending) return;
        const timer = setInterval(() => void load(), 3000);
        return () => clearInterval(timer);
    }, [pending, load]);

    const save = async (value: AgentTestInput) => {
        if (!editing) return;
        setSaving(true);
        const response = editing.id
            ? await updateAgentTestApiV1AgentTestsTestIdPut({ path: { test_id: editing.id }, body: value })
            : await createAgentTestApiV1AgentTestsPost({ body: { ...value, workflow_id } });
        setSaving(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Test non enregistré"));
            return;
        }
        setEditing(null);
        toast.success("Test enregistré");
        void load();
    };

    const run = async (test_ids?: number[]) => {
        setRunning(true);
        const response = await runAgentTestsApiV1AgentTestsRunPost({ body: { workflow_id, test_ids: test_ids ?? null, version } });
        setRunning(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Tests non lancés"));
            return;
        }
        toast.success(`${(response.data as unknown[]).length} test(s) lancé(s)`);
        void load();
    };

    const suggest = async () => {
        setSuggesting(true);
        const response = await suggestAgentTestsApiV1AgentTestsSuggestPost({ body: { workflow_id, count: 4 } });
        setSuggesting(false);
        if (response.error) {
            toast.error(detailFromError(response.error, "Propositions indisponibles"));
            return;
        }
        setSuggestions(response.data as unknown as AgentTestInput[]);
    };

    const addSuggestion = async (value: AgentTestInput, index: number) => {
        const response = await createAgentTestApiV1AgentTestsPost({ body: { ...value, workflow_id } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Test non ajouté"));
            return;
        }
        setSuggestions((s) => (s ? s.filter((_, i) => i !== index) : s));
        void load();
    };

    const remove = async (test: AgentTest) => {
        if (!window.confirm(`Supprimer le test « ${test.name} » et ses résultats ?`)) return;
        const response = await deleteAgentTestApiV1AgentTestsTestIdDelete({ path: { test_id: test.id } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Suppression impossible"));
            return;
        }
        void load();
    };

    return (
        <PageLayout
            title="Tests avec des clients simulés"
            description="Le modèle de langage de l'entreprise joue des clients face à cet agent — mêmes consignes, outils et étapes qu'un appel réel, outils simulés — puis juge chaque conversation selon vos critères."
            width="full"
            actions={
                <Button variant="ghost" size="sm" asChild>
                    <Link href={`/workflow/${workflow_id}`}>
                        <ArrowLeft /> Retour à l&apos;agent
                    </Link>
                </Button>
            }
        >
            <PageSection
                title="Tests"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <Select value={version} onValueChange={(v) => setVersion(v as "draft" | "published")}>
                            <SelectTrigger className="w-44" aria-label="Version testée">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="draft">Brouillon en cours</SelectItem>
                                <SelectItem value="published">Version publiée</SelectItem>
                            </SelectContent>
                        </Select>
                        <Button variant="outline" size="sm" onClick={suggest} disabled={suggesting}>
                            {suggesting ? <Loader2 className="animate-spin" /> : <Sparkles />} Proposer des tests
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setEditing({ id: null, value: EMPTY_TEST })}>
                            <Plus /> Nouveau test
                        </Button>
                        <Button size="sm" onClick={() => run()} disabled={running || !tests?.length}>
                            {running ? <Loader2 className="animate-spin" /> : <Play />} Lancer tous les tests
                        </Button>
                    </div>
                }
            >
                {tests === null ? (
                    <p className="text-sm text-muted-foreground">Chargement…</p>
                ) : tests.length === 0 ? (
                    <div className="py-10 text-center text-sm text-muted-foreground">
                        <FlaskConical className="mx-auto mb-2 size-6" aria-hidden />
                        Aucun test. « Proposer des tests » en prépare à partir des consignes de l&apos;agent.
                    </div>
                ) : (
                    <Table data-testid="agent-tests">
                        <TableHeader>
                            <TableRow>
                                <TableHead>Test</TableHead>
                                <TableHead>Dernier résultat</TableHead>
                                <TableHead>Fin de la conversation</TableHead>
                                <TableHead className="text-right">Actions</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {tests.map((t) => (
                                <TableRow key={t.id}>
                                    <TableCell>
                                        <p className="font-medium">{t.name}</p>
                                        <p className="line-clamp-1 text-xs text-muted-foreground">{t.persona}</p>
                                    </TableCell>
                                    <TableCell>
                                        {t.last_run ? (
                                            <button type="button" className="text-left" onClick={() => setOpenRun({ id: t.last_run!.id, name: t.name })}>
                                                <Badge variant={t.last_run.status === "passed" ? "secondary" : "outline"}>
                                                    {isPending(t.last_run.status) && <Loader2 className="size-3 animate-spin" />}
                                                    {STATUS_LABELS[t.last_run.status]}
                                                </Badge>
                                                {t.last_run.error && <span className="ml-2 text-xs text-destructive">{t.last_run.error}</span>}
                                            </button>
                                        ) : (
                                            <span className="text-sm text-muted-foreground">Jamais lancé</span>
                                        )}
                                    </TableCell>
                                    <TableCell className="text-sm text-muted-foreground">{t.last_run?.outcome_label ?? "—"}</TableCell>
                                    <TableCell className="whitespace-nowrap text-right">
                                        <Button variant="ghost" size="icon" aria-label={`Lancer ${t.name}`} disabled={running || isPending(t.last_run?.status)} onClick={() => run([t.id])}>
                                            <Play />
                                        </Button>
                                        <Button variant="ghost" size="icon" aria-label={`Modifier ${t.name}`} onClick={() => setEditing({ id: t.id, value: t })}>
                                            <Pencil />
                                        </Button>
                                        <Button variant="ghost" size="icon" aria-label={`Supprimer ${t.name}`} onClick={() => remove(t)}>
                                            <Trash2 />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </PageSection>

            <TestEditor
                open={editing !== null}
                initial={editing?.value ?? null}
                title={editing?.id ? "Modifier le test" : "Nouveau test"}
                saving={saving}
                onClose={() => setEditing(null)}
                onSave={save}
            />
            <RunSheet runId={openRun?.id ?? null} testName={openRun?.name ?? ""} onClose={() => setOpenRun(null)} />
            <Dialog open={suggestions !== null} onOpenChange={(v) => !v && setSuggestions(null)}>
                <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>Tests proposés</DialogTitle>
                        <DialogDescription>Rédigés à partir des consignes de l&apos;agent. Ajoutez ceux qui vous conviennent, puis ajustez-les.</DialogDescription>
                    </DialogHeader>
                    <ul className="space-y-3" data-testid="suggestions">
                        {suggestions?.map((s, i) => (
                            <li key={`${s.name}-${i}`} className="space-y-2 rounded-lg border p-3">
                                <p className="font-medium">{s.name}</p>
                                <p className="text-sm text-muted-foreground">{s.persona}</p>
                                {s.success_criteria.length > 0 && (
                                    <ul className="list-disc pl-5 text-sm">
                                        {s.success_criteria.map((c) => (
                                            <li key={c}>{c}</li>
                                        ))}
                                    </ul>
                                )}
                                <Button size="sm" variant="outline" onClick={() => addSuggestion(s, i)}>
                                    <Plus /> Ajouter
                                </Button>
                            </li>
                        ))}
                        {suggestions?.length === 0 && <p className="text-sm text-muted-foreground">Toutes les propositions ont été ajoutées.</p>}
                    </ul>
                </DialogContent>
            </Dialog>
        </PageLayout>
    );
}

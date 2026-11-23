"use client";

import { Bot, FileText, Loader2, Play, RefreshCw, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
    evaluateRecordingApiV1QualityRecordingsRecordingIdEvaluatePost,
    readQualityReviewApiV1QualityReviewsReviewIdGet,
    recordingAudioApiV1PbxRecordingsRecordingIdAudioGet,
    submitQualityReviewApiV1QualityReviewsReviewIdPut,
} from "@/client/sdk.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import {
    agentLabel,
    answerLabel,
    ANSWERS,
    type AnswerValue,
    durationText,
    type Review,
    scoreOf,
    scoreText,
    STATUS_LABELS,
} from "@/lib/quality";

type Draft = Record<string, { answer?: AnswerValue; comment: string }>;

/** The supervisor starts from the AI's answers (comments stay the AI's,
 * shown above each criterion), or from their own review when there is one. */
function draftOf(review: Review): Draft {
    if (review.reviewer_answers) {
        return Object.fromEntries(review.reviewer_answers.map((a) => [a.key, { answer: a.answer ?? undefined, comment: a.comment }]));
    }
    return Object.fromEntries(review.ai_answers.map((a) => [a.key, { answer: a.answer ?? undefined, comment: "" }]));
}

/** One call: listen, read, compare with the AI, validate the score. */
export function ReviewSheet({ reviewId, onClose, onSaved }: { reviewId: number | null; onClose: () => void; onSaved: () => void }) {
    const [review, setReview] = useState<Review | null>(null);
    const [draft, setDraft] = useState<Draft>({});
    const [comment, setComment] = useState("");
    const [audio, setAudio] = useState<string | null>(null);
    const [busy, setBusy] = useState<"save" | "ai" | null>(null);

    const take = (r: Review) => {
        setReview(r);
        setDraft(draftOf(r));
        setComment(r.reviewer_comment ?? "");
    };

    useEffect(() => {
        setReview(null);
        setAudio(null);
        if (reviewId === null) return;
        void (async () => {
            const response = await readQualityReviewApiV1QualityReviewsReviewIdGet({ path: { review_id: reviewId } });
            if (response.error) {
                toast.error(detailFromError(response.error, "Évaluation introuvable"));
                onClose();
                return;
            }
            take(response.data as unknown as Review);
        })();
    }, [reviewId, onClose]);

    const score = useMemo(
        () => (review ? scoreOf(review.criteria, Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, v.answer]))) : null),
        [review, draft],
    );

    const save = async () => {
        if (!review) return;
        const answers = Object.fromEntries(
            Object.entries(draft)
                .filter(([, v]) => v.answer)
                .map(([k, v]) => [k, { answer: v.answer as AnswerValue, comment: v.comment }]),
        );
        if (!Object.keys(answers).length) {
            toast.error("Répondez au moins à un critère");
            return;
        }
        setBusy("save");
        const response = await submitQualityReviewApiV1QualityReviewsReviewIdPut({ path: { review_id: review.id }, body: { answers, comment } });
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return;
        }
        take(response.data as unknown as Review);
        toast.success("Évaluation validée");
        onSaved();
    };

    const evaluateWithAi = async () => {
        if (!review) return;
        setBusy("ai");
        const response = await evaluateRecordingApiV1QualityRecordingsRecordingIdEvaluatePost({ path: { recording_id: review.recording_id } });
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Évaluation impossible"));
            return;
        }
        take(response.data as unknown as Review);
        onSaved();
    };

    return (
        <Sheet open={reviewId !== null} onOpenChange={(v) => !v && onClose()}>
            <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
                {!review ? (
                    <p className="p-6 text-sm text-muted-foreground">Chargement…</p>
                ) : (
                    <div className="space-y-5 pb-6">
                        <SheetHeader>
                            <SheetTitle>{agentLabel(review)}</SheetTitle>
                            <SheetDescription>
                                {review.started_at ? new Date(review.started_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "Date inconnue"} ·{" "}
                                {durationText(review.duration_seconds)} · {review.customer_phone ?? "client inconnu"}
                            </SheetDescription>
                        </SheetHeader>

                        <div className="flex flex-wrap items-center gap-2 px-4">
                            <Badge variant="outline">{STATUS_LABELS[review.status]}</Badge>
                            <span className="text-sm">
                                Note IA : <strong className="tabular-nums">{scoreText(review.ai_score)}</strong>
                            </span>
                            <span className="text-sm">
                                Note retenue : <strong className="tabular-nums" data-testid="draft-score">{scoreText(score)}</strong>
                            </span>
                            <span className="grow" />
                            {audio ? (
                                <audio controls autoPlay src={audio} className="h-8 w-64 max-w-full" />
                            ) : (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={async () => {
                                        const response = await recordingAudioApiV1PbxRecordingsRecordingIdAudioGet({ path: { recording_id: review.recording_id } });
                                        if (response.error || !response.data) {
                                            toast.error(detailFromError(response.error, "Écoute impossible"));
                                            return;
                                        }
                                        setAudio((response.data as { url: string }).url);
                                    }}
                                >
                                    <Play /> Écouter
                                </Button>
                            )}
                            <Button variant="outline" size="sm" disabled={busy !== null || !review.transcript} onClick={evaluateWithAi} title={review.transcript ? undefined : "Pas de transcription pour cet appel"}>
                                {busy === "ai" ? <Loader2 className="animate-spin" /> : review.ai_answers.some((a) => a.answer) ? <RefreshCw /> : <Bot />}
                                {review.ai_answers.some((a) => a.answer) ? "Réévaluer avec l'IA" : "Évaluer avec l'IA"}
                            </Button>
                        </div>

                        {review.ai_error && <p className="px-4 text-sm text-destructive">IA : {review.ai_error}</p>}
                        {review.ai_summary && <p className="mx-4 rounded-md bg-muted/40 p-3 text-sm">{review.ai_summary}</p>}

                        {review.transcript && (
                            <Collapsible className="px-4">
                                <CollapsibleTrigger asChild>
                                    <Button variant="ghost" size="sm">
                                        <FileText /> Transcription
                                    </Button>
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                    <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border p-3 text-sm">{review.transcript}</p>
                                </CollapsibleContent>
                            </Collapsible>
                        )}

                        <ol className="space-y-4 px-4" data-testid="criteria">
                            {review.criteria.map((c) => {
                                const ai = review.ai_answers.find((a) => a.key === c.key);
                                const current = draft[c.key] ?? { comment: "" };
                                return (
                                    <li key={c.key} className="space-y-2 rounded-lg border p-3">
                                        <div>
                                            <p className="font-medium">
                                                {c.label} <span className="text-xs font-normal text-muted-foreground">× {c.weight}</span>
                                            </p>
                                            {c.description && <p className="text-xs text-muted-foreground">{c.description}</p>}
                                        </div>
                                        {ai?.answer && (
                                            <p className="text-xs text-muted-foreground">
                                                <Bot className="mr-1 inline size-3" aria-label="IA" />
                                                <strong>{answerLabel(ai.answer)}</strong>
                                                {ai.comment && ` — ${ai.comment}`}
                                            </p>
                                        )}
                                        <RadioGroup
                                            className="flex flex-wrap gap-4"
                                            value={current.answer ?? ""}
                                            onValueChange={(v) => setDraft((d) => ({ ...d, [c.key]: { ...current, answer: v as AnswerValue } }))}
                                            aria-label={c.label}
                                        >
                                            {ANSWERS.map((a) => (
                                                <Label key={a.value} className="flex items-center gap-1.5 text-sm font-normal">
                                                    <RadioGroupItem value={a.value} /> {a.label}
                                                </Label>
                                            ))}
                                        </RadioGroup>
                                        <Input
                                            placeholder="Commentaire (facultatif)"
                                            value={current.comment}
                                            maxLength={500}
                                            onChange={(e) => setDraft((d) => ({ ...d, [c.key]: { ...current, comment: e.target.value } }))}
                                        />
                                    </li>
                                );
                            })}
                        </ol>

                        <div className="space-y-2 px-4">
                            <Label htmlFor="review-comment">Retour au conseiller</Label>
                            <Textarea id="review-comment" value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} placeholder="Points forts, axes de progrès…" />
                        </div>
                        <div className="flex justify-end px-4">
                            <Button onClick={save} disabled={busy !== null}>
                                {busy === "save" ? <Loader2 className="animate-spin" /> : <Save />} Valider l&apos;évaluation
                            </Button>
                        </div>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

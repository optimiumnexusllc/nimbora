"use client";

import { Loader2, Music, Upload, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getHoldMusicApiV1PbxHoldMusicGet,
    holdMusicSampleApiV1PbxHoldMusicSampleGet,
    previewPromptApiV1PbxPromptsPreviewPost,
    publishHoldMusicApiV1PbxHoldMusicPost,
    removeHoldMusicApiV1PbxHoldMusicDelete,
} from "@/client/sdk.gen";
import type { HoldMusicState, WorkflowSummaryResponse } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

type MusicChoice = "generated" | "custom" | "none";

function play(blob: Blob) {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    void audio.play().catch(() => toast.error("Lecture bloquée par le navigateur"));
}

/** What callers hear while they wait in the company's queues and parking lots. */
export function HoldMusicCard({ workflows }: { workflows: WorkflowSummaryResponse[] }) {
    const { user, loading: authLoading } = useAuth();
    const hasFetched = useRef(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const [state, setState] = useState<HoldMusicState | null>(null);
    const [music, setMusic] = useState<MusicChoice>("generated");
    const [file, setFile] = useState<File | null>(null);
    const [announcement, setAnnouncement] = useState("");
    const [voice, setVoice] = useState("org");
    const [busy, setBusy] = useState<"publish" | "remove" | "sample" | "voice" | null>(null);

    const apply = (data: HoldMusicState) => {
        setState(data);
        setAnnouncement((current) => current || data.suggested_announcement);
    };

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void getHoldMusicApiV1PbxHoldMusicGet().then((response) => {
            if (response.error) {
                toast.error(detailFromError(response.error, "Musique d'attente indisponible"));
                return;
            }
            if (response.data) apply(response.data);
        });
    }, [authLoading, user]);

    const voiceWorkflowId = voice === "org" ? null : Number(voice);
    const nothing = music === "none" && !announcement.trim();
    const missingFile = music === "custom" && !file;

    async function publish() {
        setBusy("publish");
        const response = await publishHoldMusicApiV1PbxHoldMusicPost({
            body: {
                music,
                announcement: announcement.trim(),
                ...(voiceWorkflowId ? { voice_workflow_id: voiceWorkflowId } : {}),
                ...(music === "custom" && file ? { music_file: file } : {}),
            },
        });
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Publication impossible"));
            return;
        }
        if (response.data) apply(response.data);
        toast.success("Musique d'attente publiée sur le PBX");
    }

    async function remove() {
        setBusy("remove");
        const response = await removeHoldMusicApiV1PbxHoldMusicDelete();
        setBusy(null);
        if (response.error) {
            toast.error(detailFromError(response.error, "Retrait impossible"));
            return;
        }
        setState((current) => (current ? { ...current, active: false, music: false, announcement: false, queues: 0, parking_lots: 0 } : current));
        toast.success("Musique par défaut du PBX rétablie");
    }

    async function listen(kind: "sample" | "voice") {
        setBusy(kind);
        const response =
            kind === "sample"
                ? await holdMusicSampleApiV1PbxHoldMusicSampleGet({ parseAs: "blob" })
                : await previewPromptApiV1PbxPromptsPreviewPost({
                      body: { text: announcement, voice_workflow_id: voiceWorkflowId },
                      parseAs: "blob",
                  });
        setBusy(null);
        if (response.error || !(response.data instanceof Blob)) {
            toast.error(detailFromError(response.error, "Écoute impossible"));
            return;
        }
        play(response.data);
    }

    return (
        <PageSection
            title="Musique d'attente"
            description="Ce qu'entendent les appelants en attente dans vos files et vos parcages : une musique et, si vous le souhaitez, une annonce dite avec votre voix, en boucle."
        >
            <div className="space-y-5 rounded-xl border border-border/60 p-4" data-testid="hold-music">
                <p className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
                    {state === null ? (
                        <span className="text-muted-foreground">Chargement…</span>
                    ) : state.active ? (
                        <>
                            <Badge>En service</Badge>
                            <span className="text-muted-foreground">
                                {state.queues} file{state.queues > 1 ? "s" : ""} et {state.parking_lots} parcage
                                {state.parking_lots > 1 ? "s" : ""}
                                {state.announcement ? " · avec annonce" : ""}
                            </span>
                        </>
                    ) : (
                        <span className="text-muted-foreground">Musique par défaut du PBX.</span>
                    )}
                </p>

                <div className="space-y-2">
                    <Label>Musique</Label>
                    <RadioGroup value={music} onValueChange={(v) => setMusic(v as MusicChoice)} aria-label="Musique" className="gap-2">
                        <label className="flex items-center gap-2 text-sm">
                            <RadioGroupItem value="generated" /> Musique générée par la plateforme (libre de droits)
                            <Button type="button" variant="ghost" size="sm" disabled={busy !== null} onClick={() => void listen("sample")} aria-label="Écouter la musique générée">
                                {busy === "sample" ? <Loader2 className="animate-spin" /> : <Volume2 />} Écouter
                            </Button>
                        </label>
                        <label className="flex flex-wrap items-center gap-2 text-sm">
                            <RadioGroupItem value="custom" /> Votre musique (WAV, 10 minutes au plus)
                            <input
                                ref={fileInput}
                                type="file"
                                accept=".wav,audio/wav"
                                className="hidden"
                                onChange={(e) => {
                                    setFile(e.target.files?.[0] ?? null);
                                    setMusic("custom");
                                }}
                            />
                            <Button type="button" variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
                                <Upload /> Choisir un fichier
                            </Button>
                            {file && <span className="text-muted-foreground">{file.name}</span>}
                        </label>
                        <label className="flex items-center gap-2 text-sm">
                            <RadioGroupItem value="none" /> Pas de musique (l&apos;annonce seule, toutes les 20 secondes)
                        </label>
                    </RadioGroup>
                </div>

                <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                    <div className="space-y-1">
                        <div className="flex items-center justify-between">
                            <Label htmlFor="hold-announcement">Annonce (facultative)</Label>
                            <Button type="button" variant="ghost" size="sm" disabled={!announcement.trim() || busy !== null} onClick={() => void listen("voice")} aria-label="Écouter l'annonce">
                                {busy === "voice" ? <Loader2 className="animate-spin" /> : <Volume2 />} Écouter
                            </Button>
                        </div>
                        <Textarea
                            id="hold-announcement"
                            value={announcement}
                            maxLength={800}
                            onChange={(e) => setAnnouncement(e.target.value)}
                            placeholder="Merci de patienter…"
                        />
                        <p className="text-xs text-muted-foreground">Écrite dans la langue que vos appelants parlent : la voix la lit telle quelle. Laissez vide pour la musique seule.</p>
                    </div>
                    <div className="space-y-1">
                        <Label>Voix</Label>
                        <Select value={voice} onValueChange={setVoice}>
                            <SelectTrigger aria-label="Voix de l'annonce" className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="org">Voix par défaut de l&apos;organisation</SelectItem>
                                {workflows.map((w) => (
                                    <SelectItem key={w.id} value={String(w.id)}>
                                        Voix de l&apos;agent « {w.name} »
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>

                <div className="flex flex-wrap gap-2">
                    <Button type="button" onClick={() => void publish()} disabled={busy !== null || nothing || missingFile}>
                        {busy === "publish" ? <Loader2 className="animate-spin" /> : <Music />} Publier sur le PBX
                    </Button>
                    {state?.active && (
                        <Button type="button" variant="outline" onClick={() => void remove()} disabled={busy !== null}>
                            {busy === "remove" && <Loader2 className="animate-spin" />} Revenir à la musique du PBX
                        </Button>
                    )}
                </div>
            </div>
        </PageSection>
    );
}

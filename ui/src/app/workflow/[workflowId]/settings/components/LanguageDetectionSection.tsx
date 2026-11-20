"use client";

import { Languages, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { LanguageDetectionConfiguration } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useUnsavedChanges } from "@/context/UnsavedChangesContext";
import { useAuth } from "@/lib/auth";
import { enterpriseApi, type LocalAIInfo } from "@/lib/enterpriseApi";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

/** Languages offered even when the self-hosted stack is not deployed. */
const COMMON_LANGUAGES: { code: string; name: string }[] = [
    { code: "fr", name: "Français" },
    { code: "en", name: "English" },
    { code: "es", name: "Español" },
    { code: "pt", name: "Português" },
    { code: "ar", name: "العربية" },
    { code: "de", name: "Deutsch" },
    { code: "it", name: "Italiano" },
    { code: "sw", name: "Kiswahili" },
    { code: "ha", name: "Hausa" },
    { code: "yo", name: "Yorùbá" },
    { code: "ln", name: "Lingála" },
    { code: "zh", name: "中文" },
];

type VoiceOverride = { voice: string; model?: string | null };

const EMPTY: LanguageDetectionConfiguration = {
    enabled: false,
    default_language: null,
    languages: [],
    voices: {},
    remember_caller_language: true,
};

export function normalizeLanguageDetection(
    value: Partial<LanguageDetectionConfiguration> | null | undefined,
): LanguageDetectionConfiguration {
    return {
        ...EMPTY,
        ...(value ?? {}),
        languages: [...(value?.languages ?? [])],
        voices: { ...(value?.voices ?? {}) },
    };
}

export function LanguageDetectionSection({
    workflowConfigurations,
    onSave,
}: {
    workflowConfigurations: WorkflowConfigurations;
    onSave: (value: WorkflowConfigurations) => Promise<void>;
}) {
    const { user, loading: authLoading } = useAuth();
    const saved = useMemo(
        () =>
            normalizeLanguageDetection(
                workflowConfigurations.language_detection as Partial<LanguageDetectionConfiguration> | undefined,
            ),
        [workflowConfigurations.language_detection],
    );
    const [config, setConfig] = useState<LanguageDetectionConfiguration>(saved);
    const [catalog, setCatalog] = useState<LocalAIInfo | null>(null);
    const [saving, setSaving] = useState(false);
    const fetched = useRef(false);

    useEffect(() => setConfig(saved), [saved]);

    useEffect(() => {
        if (authLoading || !user || fetched.current) return;
        fetched.current = true;
        enterpriseApi
            .localLanguages()
            .then(setCatalog)
            .catch(() => setCatalog(null));
    }, [authLoading, user]);

    const dirty = JSON.stringify(config) !== JSON.stringify(saved);
    useUnsavedChanges("languages", dirty);

    const languages = useMemo(() => {
        const list = catalog?.languages?.length
            ? catalog.languages.map((l) => ({ code: l.code, name: l.name }))
            : COMMON_LANGUAGES;
        return list;
    }, [catalog]);
    const nameOf = (code: string) => languages.find((l) => l.code === code)?.name ?? code;
    const packVoices = (code: string) => catalog?.languages.find((l) => l.code === code)?.voices ?? [];

    const allowed = config.languages ?? [];
    const voices = (config.voices ?? {}) as Record<string, VoiceOverride>;
    const toggleLanguage = (code: string) =>
        setConfig((c) => {
            const list = c.languages ?? [];
            return { ...c, languages: list.includes(code) ? list.filter((l) => l !== code) : [...list, code] };
        });
    const setVoice = (code: string, value: VoiceOverride | null) =>
        setConfig((c) => {
            const next = { ...((c.voices ?? {}) as Record<string, VoiceOverride>) };
            if (value && value.voice.trim()) next[code] = value;
            else delete next[code];
            return { ...c, voices: next };
        });

    const save = async () => {
        setSaving(true);
        try {
            await onSave({ ...workflowConfigurations, language_detection: config });
            toast.success("Language settings saved. Publish the agent to apply them to new calls.");
        } catch {
            toast.error("Could not save language settings");
        } finally {
            setSaving(false);
        }
    };

    const voiceLanguages = allowed.length ? allowed : languages.slice(0, 6).map((l) => l.code);

    return (
        <Card id="languages">
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Languages className="h-4 w-4" />
                    Languages
                </CardTitle>
                <CardDescription>
                    Follow the caller&apos;s language: when they switch language, the agent replies in theirs with a
                    matching voice. Needs a multilingual speech recognizer (self-hosted Whisper with language
                    &quot;auto&quot;, Deepgram &quot;multi&quot;…).
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <div className="flex items-center justify-between gap-4">
                    <Label htmlFor="language-detection-enabled">Detect the caller&apos;s language automatically</Label>
                    <Switch
                        id="language-detection-enabled"
                        checked={config.enabled ?? false}
                        onCheckedChange={(enabled) => setConfig((c) => ({ ...c, enabled }))}
                    />
                </div>

                {config.enabled && (
                    <>
                        <div className="grid gap-2 sm:max-w-xs">
                            <Label>Starting language</Label>
                            <Select
                                value={config.default_language ?? "__stt__"}
                                onValueChange={(v) =>
                                    setConfig((c) => ({ ...c, default_language: v === "__stt__" ? null : v }))
                                }
                            >
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__stt__">Same as the speech recognizer</SelectItem>
                                    {languages.map((l) => (
                                        <SelectItem key={l.code} value={l.code}>
                                            {l.name} ({l.code})
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-2">
                            <Label>Languages the agent may switch to</Label>
                            <p className="text-xs text-muted-foreground">
                                None selected: any language. Restricting avoids switching on a stray word.
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {languages.map((l) => {
                                    const on = allowed.includes(l.code);
                                    return (
                                        <button
                                            key={l.code}
                                            type="button"
                                            aria-pressed={on}
                                            onClick={() => toggleLanguage(l.code)}
                                            className={`rounded-full border px-3 py-1 text-xs transition ${
                                                on
                                                    ? "border-primary bg-primary/15 text-foreground"
                                                    : "border-border/60 text-muted-foreground hover:bg-accent/40"
                                            }`}
                                        >
                                            {l.name}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label>Voice per language</Label>
                            <p className="text-xs text-muted-foreground">
                                Optional. Without a choice, self-hosted voices come from the language pack and cloud
                                multilingual voices keep the same voice in the new language.
                            </p>
                            <div className="divide-y divide-border/50 rounded-lg border border-border/60">
                                {voiceLanguages.map((code) => {
                                    const current = voices[code];
                                    const options = packVoices(code);
                                    return (
                                        <div key={code} className="flex flex-wrap items-center gap-3 px-3 py-2">
                                            <Badge variant="secondary" className="w-28 justify-center">
                                                {nameOf(code)}
                                            </Badge>
                                            {options.length > 0 ? (
                                                <Select
                                                    value={current ? `${current.model ?? ""}|${current.voice}` : "__auto__"}
                                                    onValueChange={(v) => {
                                                        if (v === "__auto__") return setVoice(code, null);
                                                        const [model, voice] = v.split("|");
                                                        setVoice(code, { voice, model: model || null });
                                                    }}
                                                >
                                                    <SelectTrigger className="w-64">
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="__auto__">Automatic</SelectItem>
                                                        {options.map((o) => (
                                                            <SelectItem key={`${o.model}|${o.voice}`} value={`${o.model}|${o.voice}`}>
                                                                {o.label}
                                                            </SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                            ) : (
                                                <Input
                                                    className="w-64"
                                                    placeholder="Automatic (voice id)"
                                                    value={current?.voice ?? ""}
                                                    onChange={(e) =>
                                                        setVoice(code, { voice: e.target.value, model: current?.model ?? null })
                                                    }
                                                />
                                            )}
                                            {current && (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    aria-label={`Reset the ${nameOf(code)} voice`}
                                                    onClick={() => setVoice(code, null)}
                                                >
                                                    <X className="h-4 w-4" />
                                                </Button>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <Label htmlFor="remember-caller-language">Remember each caller&apos;s language</Label>
                                <p className="text-xs text-muted-foreground">
                                    Known callers are greeted in the language of their last call (customer memory).
                                </p>
                            </div>
                            <Switch
                                id="remember-caller-language"
                                checked={config.remember_caller_language ?? true}
                                onCheckedChange={(remember_caller_language) =>
                                    setConfig((c) => ({ ...c, remember_caller_language }))
                                }
                            />
                        </div>
                    </>
                )}
            </CardContent>
            <CardFooter className="justify-end gap-3 border-t pt-6">
                {dirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
                <Button onClick={save} disabled={!dirty || saving || authLoading || !user}>
                    {saving ? "Saving…" : "Save Language Settings"}
                </Button>
            </CardFooter>
        </Card>
    );
}

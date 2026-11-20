"use client";

import { Bot, Headset } from "lucide-react";

import type { ScheduleCallbackConfig } from "@/client/types.gen";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import type { TransferAgentWorkflowOption } from "./TransferAgentToolConfig";

export type CallbackAssignee = NonNullable<ScheduleCallbackConfig["assign_to"]>;

export interface CallbackQueueOption {
    slug: string;
    name: string;
}

export interface ScheduleCallbackToolConfigProps {
    name: string;
    onNameChange: (name: string) => void;
    description: string;
    onDescriptionChange: (description: string) => void;
    assignTo: CallbackAssignee;
    onAssignToChange: (assignTo: CallbackAssignee) => void;
    /** "" = the whole team. */
    queueSlug: string;
    onQueueSlugChange: (slug: string) => void;
    /** Contact-center queues; null when the human contact center is unavailable. */
    queues: CallbackQueueOption[] | null;
    workflowId: string;
    onWorkflowIdChange: (workflowId: string) => void;
    workflows: TransferAgentWorkflowOption[];
    defaultDelayMinutes: number;
    onDefaultDelayMinutesChange: (minutes: number) => void;
}

const ASSIGNEES: { value: CallbackAssignee; label: string; hint: string; icon: typeof Bot }[] = [
    {
        value: "human",
        label: "Your team",
        hint: "The callback appears in Contact center → Callbacks; an agent calls back in one click.",
        icon: Headset,
    },
    {
        value: "ai",
        label: "An AI agent",
        hint: "At the scheduled time the chosen agent calls the customer automatically (3 attempts, 15 min apart).",
        icon: Bot,
    },
];

export function ScheduleCallbackToolConfig({
    name,
    onNameChange,
    description,
    onDescriptionChange,
    assignTo,
    onAssignToChange,
    queueSlug,
    onQueueSlugChange,
    queues,
    workflowId,
    onWorkflowIdChange,
    workflows,
    defaultDelayMinutes,
    onDefaultDelayMinutesChange,
}: ScheduleCallbackToolConfigProps) {
    return (
        <Card>
            <CardHeader>
                <CardTitle>Schedule Callback Configuration</CardTitle>
                <CardDescription>
                    The agent asks the customer when to call back and why; the callback is saved with the
                    caller&apos;s number. One open callback per customer: a new request updates it.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <div className="space-y-2">
                    <Label htmlFor="tool-name">Tool Name</Label>
                    <Input id="tool-name" value={name} onChange={(e) => onNameChange(e.target.value)} />
                </div>
                <div className="space-y-2">
                    <Label htmlFor="tool-description">Description</Label>
                    <p className="text-xs text-muted-foreground">
                        Tell the agent when to offer a callback (busy line, outside opening hours, the customer
                        prefers to be called later…).
                    </p>
                    <Textarea
                        id="tool-description"
                        rows={3}
                        value={description}
                        onChange={(e) => onDescriptionChange(e.target.value)}
                    />
                </div>

                <div className="space-y-2">
                    <Label>Who calls back</Label>
                    <div className="grid gap-2 sm:grid-cols-2">
                        {ASSIGNEES.map(({ value, label, hint, icon: Icon }) => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={assignTo === value}
                                onClick={() => onAssignToChange(value)}
                                className={`rounded-lg border p-3 text-left transition ${
                                    assignTo === value
                                        ? "border-primary bg-primary/10"
                                        : "border-border/60 hover:bg-accent/40"
                                }`}
                            >
                                <span className="flex items-center gap-2 text-sm font-medium">
                                    <Icon className="h-4 w-4" />
                                    {label}
                                </span>
                                <span className="mt-1 block text-xs text-muted-foreground">{hint}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {assignTo === "human" ? (
                    <div className="space-y-2">
                        <Label>Queue</Label>
                        {queues === null ? (
                            <p className="text-xs text-muted-foreground">
                                The human contact center is not available on this plan; callbacks go to the whole
                                team.
                            </p>
                        ) : (
                            <Select
                                value={queueSlug || "__all__"}
                                onValueChange={(v) => onQueueSlugChange(v === "__all__" ? "" : v)}
                            >
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__all__">Whole team</SelectItem>
                                    {queues.map((q) => (
                                        <SelectItem key={q.slug} value={q.slug}>
                                            {q.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}
                    </div>
                ) : (
                    <div className="space-y-2">
                        <Label>Agent that calls back</Label>
                        <Select value={workflowId} onValueChange={onWorkflowIdChange}>
                            <SelectTrigger>
                                <SelectValue placeholder="Choose an agent" />
                            </SelectTrigger>
                            <SelectContent>
                                {workflows.map((w) => (
                                    <SelectItem key={w.id} value={String(w.id)}>
                                        {w.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                            The agent receives <code>{"{{callback_reason}}"}</code> and{" "}
                            <code>{"{{customer_name}}"}</code> in its context.
                        </p>
                    </div>
                )}

                <div className="space-y-2">
                    <Label htmlFor="callback-delay">Delay for &quot;as soon as possible&quot; (minutes)</Label>
                    <Input
                        id="callback-delay"
                        type="number"
                        min={0}
                        max={10080}
                        className="w-40"
                        value={defaultDelayMinutes}
                        onChange={(e) => onDefaultDelayMinutesChange(Math.max(0, Number(e.target.value) || 0))}
                    />
                </div>
            </CardContent>
        </Card>
    );
}

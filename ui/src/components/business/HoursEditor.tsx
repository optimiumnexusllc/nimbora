"use client";

import { CalendarOff, Copy, Plus, X } from "lucide-react";

import type { Closure, TimeRange } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

import { DAY_LABELS, DAYS } from "./profile";

const DEFAULT_RANGE: TimeRange = { open: "08:00", close: "18:00" };

export function HoursEditor({
    hours,
    onChange,
}: {
    hours: Record<string, TimeRange[]>;
    onChange: (hours: Record<string, TimeRange[]>) => void;
}) {
    const setDay = (day: string, ranges: TimeRange[]) => onChange({ ...hours, [day]: ranges });
    const copyMonday = () => {
        const monday = hours.mon ?? [];
        onChange({ ...hours, tue: [...monday], wed: [...monday], thu: [...monday], fri: [...monday] });
    };

    return (
        <div className="space-y-2">
            {DAYS.map((day) => {
                const ranges = hours[day] ?? [];
                const open = ranges.length > 0;
                return (
                    <div
                        key={day}
                        data-testid={`hours-${day}`}
                        className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 px-3 py-2"
                    >
                        <Switch
                            checked={open}
                            aria-label={`${DAY_LABELS[day]} ouvert`}
                            onCheckedChange={(on) => setDay(day, on ? [{ ...DEFAULT_RANGE }] : [])}
                        />
                        <span className="w-24 text-sm font-medium">{DAY_LABELS[day]}</span>
                        {!open ? (
                            <span className="text-sm text-muted-foreground">Fermé</span>
                        ) : (
                            <div className="flex flex-1 flex-wrap items-center gap-2">
                                {ranges.map((range, index) => (
                                    <div key={index} className="flex items-center gap-1">
                                        <Input
                                            type="time"
                                            aria-label={`${DAY_LABELS[day]} ouverture ${index + 1}`}
                                            className="h-8 w-[124px]"
                                            value={range.open}
                                            onChange={(e) =>
                                                setDay(day, ranges.map((r, i) => (i === index ? { ...r, open: e.target.value } : r)))
                                            }
                                        />
                                        <span className="text-muted-foreground">–</span>
                                        <Input
                                            type="time"
                                            aria-label={`${DAY_LABELS[day]} fermeture ${index + 1}`}
                                            className="h-8 w-[124px]"
                                            value={range.close}
                                            onChange={(e) =>
                                                setDay(day, ranges.map((r, i) => (i === index ? { ...r, close: e.target.value } : r)))
                                            }
                                        />
                                        {ranges.length > 1 && (
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="size-7"
                                                aria-label="Retirer la plage"
                                                onClick={() => setDay(day, ranges.filter((_, i) => i !== index))}
                                            >
                                                <X />
                                            </Button>
                                        )}
                                    </div>
                                ))}
                                {ranges.length < 4 && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => setDay(day, [...ranges, { open: "14:00", close: "18:00" }])}
                                    >
                                        <Plus /> Plage
                                    </Button>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
            <Button variant="outline" size="sm" onClick={copyMonday} disabled={!hours.mon?.length}>
                <Copy /> Appliquer les horaires du lundi au vendredi
            </Button>
        </div>
    );
}

export function ClosuresEditor({
    closures,
    onChange,
}: {
    closures: Closure[];
    onChange: (closures: Closure[]) => void;
}) {
    return (
        <div className="space-y-2">
            {closures.map((closure, index) => (
                <div key={index} className="flex items-center gap-2">
                    <Input
                        type="date"
                        aria-label="Date de fermeture"
                        className="w-44"
                        value={closure.date}
                        onChange={(e) => onChange(closures.map((c, i) => (i === index ? { ...c, date: e.target.value } : c)))}
                    />
                    <Input
                        placeholder="Motif (ex. Noël)"
                        aria-label="Motif de fermeture"
                        value={closure.label ?? ""}
                        onChange={(e) => onChange(closures.map((c, i) => (i === index ? { ...c, label: e.target.value } : c)))}
                    />
                    <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Retirer la fermeture"
                        onClick={() => onChange(closures.filter((_, i) => i !== index))}
                    >
                        <X />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => onChange([...closures, { date: "", label: "" }])}>
                <CalendarOff /> Ajouter une fermeture exceptionnelle
            </Button>
        </div>
    );
}

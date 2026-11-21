"use client";

import { BellRing, Siren, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { SupervisionAlert } from "./types";

function notificationsSupported(): boolean {
    return typeof window !== "undefined" && "Notification" in window;
}

/**
 * Supervision alerts, as they happen: a banner for everyone looking, and a
 * browser notification (if allowed) for each alert that starts, so a
 * supervisor working in another tab still knows.
 */
export function AlertsBanner({ alerts, brandName = "Supervision" }: { alerts: SupervisionAlert[]; brandName?: string }) {
    const seen = useRef<Set<string> | null>(null);
    const [permission, setPermission] = useState<NotificationPermission | "unsupported">(() =>
        notificationsSupported() ? Notification.permission : "unsupported",
    );

    useEffect(() => {
        const keys = new Set(alerts.map((a) => a.key));
        if (seen.current === null) {
            seen.current = keys; // alerts already there when the page opens are not "new"
            return;
        }
        if (permission === "granted") {
            for (const alert of alerts) {
                if (!seen.current.has(alert.key)) {
                    try {
                        new Notification(`${brandName} · ${alert.level === "critical" ? "Alerte" : "Attention"}`, {
                            body: alert.message,
                            tag: alert.key,
                        });
                    } catch {
                        // some browsers only allow notifications from a service worker
                    }
                }
            }
        }
        seen.current = keys;
    }, [alerts, permission, brandName]);

    const ask = async () => {
        if (!notificationsSupported()) return;
        setPermission(await Notification.requestPermission());
    };

    if (alerts.length === 0) {
        return permission === "default" ? (
            <div className="mb-4 flex justify-end">
                <Button variant="ghost" size="sm" onClick={ask}>
                    <BellRing className="mr-1 h-4 w-4" /> Recevoir les alertes dans le navigateur
                </Button>
            </div>
        ) : null;
    }
    return (
        <div className="mb-6 space-y-2" role="alert" data-testid="alerts-banner">
            {alerts.map((alert) => {
                const critical = alert.level === "critical";
                const Icon = critical ? Siren : TriangleAlert;
                return (
                    <div
                        key={alert.key}
                        className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm ${
                            critical
                                ? "border-red-500/50 bg-red-500/10 text-red-100"
                                : "border-amber-500/40 bg-amber-500/10 text-amber-100"
                        }`}
                    >
                        <Icon className={`h-4 w-4 shrink-0 ${critical ? "animate-pulse text-red-400" : "text-amber-400"}`} />
                        <span className="flex-1">{alert.message}</span>
                    </div>
                );
            })}
            {permission === "default" && (
                <Button variant="ghost" size="sm" onClick={ask}>
                    <BellRing className="mr-1 h-4 w-4" /> Recevoir les alertes dans le navigateur
                </Button>
            )}
        </div>
    );
}

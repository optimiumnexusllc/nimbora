"use client";

import { Apple, Globe, Laptop, Monitor, Save, Smartphone, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    listSoftphoneDevicesApiV1PbxSoftphoneDevicesGet,
    readSoftphoneSettingsApiV1PbxSoftphoneSettingsGet,
    repairWebrtcLinesApiV1PbxMaintenanceWebrtcLinesPost,
    revokeSoftphoneDeviceApiV1PbxSoftphoneDevicesDeviceIdDelete,
    saveSoftphoneSettingsApiV1PbxSoftphoneSettingsPut,
} from "@/client/sdk.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";

export type SoftphoneDevice = {
    id: number;
    name: string;
    platform: string;
    app_version: string | null;
    pbx_user_uuid: string;
    extension_name: string | null;
    last_seen_at: string | null;
    created_at: string | null;
};

const PLATFORMS: Record<string, { label: string; icon: typeof Monitor }> = {
    windows: { label: "Windows", icon: Monitor },
    macos: { label: "macOS", icon: Laptop },
    linux: { label: "Linux", icon: Monitor },
    android: { label: "Android", icon: Smartphone },
    ios: { label: "iPhone / iPad", icon: Apple },
    web: { label: "Navigateur", icon: Globe },
};

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export function SoftphonesSection() {
    const [devices, setDevices] = useState<SoftphoneDevice[] | null>(null);
    const [settings, setSettings] = useState<{ wss_url: string; sip_domain: string; overrides: Record<string, string> } | null>(null);
    const [form, setForm] = useState({ wss_url: "", sip_domain: "" });

    const load = useCallback(async () => {
        const [list, current] = await Promise.all([listSoftphoneDevicesApiV1PbxSoftphoneDevicesGet(), readSoftphoneSettingsApiV1PbxSoftphoneSettingsGet()]);
        setDevices(list.error ? [] : ((list.data as unknown as SoftphoneDevice[]) ?? []));
        if (!current.error && current.data) {
            const data = current.data as unknown as { wss_url: string; sip_domain: string; overrides: Record<string, string> };
            setSettings(data);
            setForm({ wss_url: data.overrides.wss_url ?? "", sip_domain: data.overrides.sip_domain ?? "" });
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    return (
        <PageSection
            title="Softphones"
            description="Les appareils jumelés avec NIMBORA Softphone (Windows, macOS, Linux, Android, iPhone, navigateur). Révoquez-en un et il ne peut plus appeler."
        >
            {devices === null ? null : devices.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">Aucun appareil : bouton « Softphone » sur un poste pour en jumeler un.</p>
            ) : (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Appareil</TableHead>
                            <TableHead>Poste</TableHead>
                            <TableHead>Version</TableHead>
                            <TableHead>Dernière connexion</TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {devices.map((d) => {
                            const platform = PLATFORMS[d.platform] ?? PLATFORMS.web;
                            return (
                                <TableRow key={d.id} data-testid="softphone-device">
                                    <TableCell>
                                        <span className="flex items-center gap-2">
                                            <platform.icon className="size-4 text-brand-cyan" />
                                            <span>
                                                {d.name}
                                                <span className="block text-xs text-muted-foreground">{platform.label}</span>
                                            </span>
                                        </span>
                                    </TableCell>
                                    <TableCell className="text-sm">{d.extension_name ?? "—"}</TableCell>
                                    <TableCell className="font-mono text-xs">{d.app_version ?? "—"}</TableCell>
                                    <TableCell className="text-sm text-muted-foreground">{fmt(d.last_seen_at)}</TableCell>
                                    <TableCell className="text-right">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            className="text-destructive"
                                            aria-label={`Révoquer ${d.name}`}
                                            onClick={async () => {
                                                if (!window.confirm(`Révoquer « ${d.name} » ? L'application devra être réactivée.`)) return;
                                                const response = await revokeSoftphoneDeviceApiV1PbxSoftphoneDevicesDeviceIdDelete({ path: { device_id: d.id } });
                                                if (response.error) {
                                                    toast.error(detailFromError(response.error, "Révocation impossible"));
                                                    return;
                                                }
                                                toast.success("Appareil révoqué");
                                                void load();
                                            }}
                                        >
                                            <Trash2 /> Révoquer
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            )}
            {settings && (
                <details className="mt-4 rounded-lg border border-border/60 p-3" data-testid="softphone-settings">
                    <summary className="cursor-pointer text-sm font-medium">Connexion des softphones au PBX</summary>
                    <p className="mt-2 text-sm text-muted-foreground">
                        Par défaut : <span className="font-mono">{settings.wss_url}</span>, domaine <span className="font-mono">{settings.sip_domain}</span>. À
                        changer seulement si le PBX est derrière un autre nom ou un proxy.
                    </p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                        <div className="space-y-1">
                            <Label htmlFor="softphone-wss">WebSocket sécurisé</Label>
                            <Input id="softphone-wss" placeholder="wss://voix.exemple.com/api/asterisk/ws" value={form.wss_url} onChange={(e) => setForm({ ...form, wss_url: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="softphone-domain">Domaine SIP</Label>
                            <Input id="softphone-domain" placeholder="voix.exemple.com" value={form.sip_domain} onChange={(e) => setForm({ ...form, sip_domain: e.target.value })} />
                        </div>
                        <Button
                            variant="outline"
                            onClick={async () => {
                                const response = await saveSoftphoneSettingsApiV1PbxSoftphoneSettingsPut({ body: form });
                                if (response.error) {
                                    toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                    return;
                                }
                                toast.success("Connexion des softphones enregistrée");
                                void load();
                            }}
                        >
                            <Save /> Enregistrer
                        </Button>
                    </div>
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
                        <p className="max-w-xl text-sm text-muted-foreground">
                            Un poste navigateur qui ne sonne jamais (le PBX répond « congestion ») a été créé avant un correctif : NIMBORA le répare quand son
                            Softphone démarre, ou ici pour toutes les lignes d&apos;un coup.
                        </p>
                        <Button
                            variant="outline"
                            onClick={async () => {
                                const response = await repairWebrtcLinesApiV1PbxMaintenanceWebrtcLinesPost();
                                if (response.error || !response.data) {
                                    toast.error(detailFromError(response.error, "Réparation impossible"));
                                    return;
                                }
                                const { checked, repaired, failed } = response.data;
                                if (failed.length) toast.error(`Non réparées : ${failed.join(", ")} (droits du compte de service à mettre à jour)`);
                                else if (repaired.length) toast.success(`Lignes navigateur réparées : ${repaired.join(", ")}`);
                                else toast.success(`${checked} ligne${checked > 1 ? "s" : ""} vérifiée${checked > 1 ? "s" : ""} : rien à réparer`);
                            }}
                        >
                            <Wrench /> Vérifier les lignes navigateur
                        </Button>
                    </div>
                </details>
            )}
        </PageSection>
    );
}

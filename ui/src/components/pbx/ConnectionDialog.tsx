"use client";

import { useEffect, useState } from "react";

import type { ConnectionResponse, TelephonyConfigurationListItem } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

export type ConnectionForm = {
    name: string;
    base_url: string;
    username: string;
    password: string;
    tenant_uuid: string;
    verify_tls: boolean;
    ari_configuration_id: number | null;
    incall_context: string;
};

export function formFrom(connection: ConnectionResponse | null): ConnectionForm {
    return {
        name: connection?.name ?? "PBX",
        base_url: connection?.base_url ?? "",
        username: connection?.username ?? "nimbora-integration",
        password: connection?.password ?? "",
        tenant_uuid: connection?.tenant_uuid ?? "",
        verify_tls: connection?.verify_tls ?? true,
        ari_configuration_id: connection?.ari_configuration_id ?? null,
        incall_context: connection?.incall_context ?? "",
    };
}

export function ConnectionDialog({
    open,
    onOpenChange,
    connection,
    ariConfigurations,
    onSave,
    pbxName,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    connection: ConnectionResponse | null;
    ariConfigurations: TelephonyConfigurationListItem[];
    onSave: (form: ConnectionForm) => Promise<boolean>;
    pbxName: string;
}) {
    const [form, setForm] = useState<ConnectionForm>(formFrom(connection));
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        if (open) setForm(formFrom(connection));
    }, [open, connection]);
    const set = <K extends keyof ConnectionForm>(key: K, value: ConnectionForm[K]) => setForm({ ...form, [key]: value });
    const isNew = !connection?.configured;

    const submit = async () => {
        setBusy(true);
        const ok = await onSave(form);
        setBusy(false);
        if (ok) onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader className="min-w-0">
                    <DialogTitle>Connexion à {pbxName}</DialogTitle>
                    <DialogDescription>
                        Le compte de service et le tenant sont affichés à la fin de l&apos;installation du PBX
                        (deploy/pbx/install.sh).
                    </DialogDescription>
                </DialogHeader>
                <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                    <div className="space-y-1 sm:col-span-2">
                        <Label htmlFor="pbx-url">Adresse du PBX</Label>
                        <Input id="pbx-url" placeholder="https://pbx.votre-marque.com" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="pbx-user">Compte de service</Label>
                        <Input id="pbx-user" value={form.username} onChange={(e) => set("username", e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="pbx-pass">Mot de passe</Label>
                        <Input
                            id="pbx-pass"
                            type="password"
                            placeholder={isNew ? "" : "inchangé"}
                            value={form.password}
                            onFocus={() => form.password.startsWith("•") && set("password", "")}
                            onChange={(e) => set("password", e.target.value)}
                        />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                        <Label htmlFor="pbx-tenant">Tenant de l&apos;entreprise</Label>
                        <Input id="pbx-tenant" placeholder="uuid" value={form.tenant_uuid} onChange={(e) => set("tenant_uuid", e.target.value)} />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                        <Label>Accès des agents IA (configuration ARI)</Label>
                        <Select
                            value={form.ari_configuration_id ? String(form.ari_configuration_id) : "none"}
                            onValueChange={(v) => set("ari_configuration_id", v === "none" ? null : Number(v))}
                        >
                            <SelectTrigger aria-label="Configuration ARI" className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="none">Aucune (pas d&apos;agent IA sur le PBX)</SelectItem>
                                {ariConfigurations.map((c) => (
                                    <SelectItem key={c.id} value={String(c.id)}>
                                        {c.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                            À créer dans Téléphonie → Asterisk ARI, avec l&apos;utilisateur et le mot de passe ARI du PBX.
                        </p>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="pbx-context">Contexte des numéros entrants</Label>
                        <Input id="pbx-context" placeholder="automatique" value={form.incall_context} onChange={(e) => set("incall_context", e.target.value)} />
                    </div>
                    <div className="flex items-center gap-2 self-end pb-2">
                        <Switch id="pbx-tls" checked={form.verify_tls} onCheckedChange={(v) => set("verify_tls", v)} />
                        <Label htmlFor="pbx-tls" className="font-normal">Vérifier le certificat HTTPS</Label>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Annuler
                    </Button>
                    <Button
                        onClick={submit}
                        disabled={busy || !form.base_url.trim() || !form.username.trim() || (isNew && !form.password)}
                    >
                        Enregistrer et tester
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

"use client";

import { Copy, Download, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import type { ExtensionResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function downloadText(filename: string, content: string, type = "text/csv;charset=utf-8") {
    const blob = new Blob(["﻿" + content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
}

export function credentialsCsv(items: ExtensionResponse[]): string {
    const rows = [["nom", "poste", "identifiant", "mot_de_passe", "sip_utilisateur", "sip_mot_de_passe", "code_messagerie"]];
    for (const item of items) {
        const c = item.credentials;
        rows.push([item.name, item.extension, c.login, c.login_password, c.sip_username, c.sip_password, c.voicemail_pin ?? ""]);
    }
    return rows.map((r) => r.join(";")).join("\n") + "\n";
}

/** Secrets generated for new extensions: shown once, never stored by NIMBORA. */
export function CredentialsDialog({
    items,
    csv,
    onClose,
}: {
    items: ExtensionResponse[];
    csv?: string;
    onClose: () => void;
}) {
    const sheet = csv ?? credentialsCsv(items);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(sheet);
            toast.success("Identifiants copiés");
        } catch {
            toast.error("Copie impossible");
        }
    };
    return (
        <Dialog open={items.length > 0} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-3xl">
                <DialogHeader className="min-w-0">
                    <DialogTitle>
                        {items.length === 1 ? `Poste ${items[0].extension} créé` : `${items.length} postes créés`}
                    </DialogTitle>
                    <DialogDescription className="flex items-start gap-2">
                        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-400" />
                        Ces identifiants ne seront plus affichés : téléchargez-les ou copiez-les maintenant, puis
                        transmettez-les à chaque personne par un canal sûr.
                    </DialogDescription>
                </DialogHeader>
                <div className="max-h-80 min-w-0 overflow-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Personne</TableHead>
                                <TableHead>Identifiant</TableHead>
                                <TableHead>Mot de passe</TableHead>
                                <TableHead>Compte SIP</TableHead>
                                <TableHead>Messagerie</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {items.map((item) => (
                                <TableRow key={item.uuid} data-testid="credentials-row">
                                    <TableCell>
                                        <div className="font-medium">{item.name}</div>
                                        <div className="font-mono text-xs text-muted-foreground">poste {item.extension}</div>
                                    </TableCell>
                                    <TableCell className="font-mono text-xs">{item.credentials.login}</TableCell>
                                    <TableCell className="font-mono text-xs">{item.credentials.login_password}</TableCell>
                                    <TableCell className="font-mono text-xs">
                                        {item.credentials.sip_username}
                                        <br />
                                        {item.credentials.sip_password}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs">{item.credentials.voicemail_pin ?? "—"}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={copy}>
                        <Copy /> Copier
                    </Button>
                    <Button variant="outline" onClick={() => downloadText("identifiants-postes.csv", sheet)}>
                        <Download /> Télécharger (CSV)
                    </Button>
                    <Button onClick={onClose}>J&apos;ai enregistré les identifiants</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

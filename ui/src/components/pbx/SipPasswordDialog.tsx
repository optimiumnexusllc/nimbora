"use client";

import { Copy, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import type { SipPasswordResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** The new SIP secret of an extension, shown once. */
export function SipPasswordDialog({ result, name, onClose }: { result: SipPasswordResponse | null; name: string; onClose: () => void }) {
    const copy = async (text: string) => {
        try {
            await navigator.clipboard.writeText(text);
            toast.success("Copié");
        } catch {
            toast.error("Copie impossible");
        }
    };
    return (
        <Dialog open={result !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Nouveau mot de passe SIP · {name}</DialogTitle>
                    <DialogDescription className="flex gap-2">
                        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                        Affiché une seule fois : NIMBORA ne le conserve pas. NIMBORA Softphone le reprend tout seul ; un téléphone configuré à la main (Linphone, poste de bureau) doit recevoir ces valeurs.
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3" data-testid="sip-password">
                    {result?.lines.map((line) => (
                        <dl key={line.sip_identity ?? line.extension} className="grid grid-cols-[9rem_1fr_auto] items-center gap-x-3 gap-y-1.5 rounded-lg border border-border/60 p-3 text-sm">
                            <dt className="text-muted-foreground">Poste</dt>
                            <dd className="font-mono">{line.extension ?? "—"}</dd>
                            <span />
                            <dt className="text-muted-foreground">Utilisateur SIP</dt>
                            <dd className="font-mono">{line.sip_identity ?? "—"}</dd>
                            <span />
                            <dt className="text-muted-foreground">Authentification</dt>
                            <dd className="font-mono">{line.sip_username ?? "—"}</dd>
                            <span />
                            <dt className="text-muted-foreground">Mot de passe</dt>
                            <dd className="font-mono break-all">{line.sip_password}</dd>
                            <Button variant="ghost" size="icon" aria-label="Copier le mot de passe SIP" onClick={() => void copy(line.sip_password)}>
                                <Copy />
                            </Button>
                        </dl>
                    ))}
                </div>
                <DialogFooter>
                    <Button onClick={onClose}>J&apos;ai noté le mot de passe</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

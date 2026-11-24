"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

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

/** An invitation link, shown once: the platform keeps only its fingerprint. */
export function InvitationLinkDialog({
    url,
    title,
    onClose,
}: {
    url: string | null;
    title: string;
    onClose: () => void;
}) {
    const [copied, setCopied] = useState(false);
    return (
        <Dialog open={url !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>
                        Envoyez ce lien à la personne invitée. Il sert une seule fois, expire dans 7 jours et
                        n&apos;est affiché qu&apos;ici : copiez-le maintenant.
                    </DialogDescription>
                </DialogHeader>
                <div className="flex gap-2">
                    <Input readOnly value={url ?? ""} aria-label="Lien d'invitation" onFocus={(e) => e.target.select()} />
                    <Button
                        type="button"
                        variant="outline"
                        onClick={async () => {
                            if (!url) return;
                            await navigator.clipboard?.writeText(url).catch(() => undefined);
                            setCopied(true);
                        }}
                    >
                        {copied ? <Check /> : <Copy />} {copied ? "Copié" : "Copier"}
                    </Button>
                </div>
                <DialogFooter>
                    <Button type="button" onClick={onClose}>
                        J&apos;ai copié le lien
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

"use client";

import { Apple, Copy, Globe, Laptop, Loader2, Monitor, Smartphone } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { createSoftphoneActivationApiV1PbxExtensionsUserUuidSoftphonePost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { useBrand } from "@/context/BrandContext";
import { detailFromError } from "@/lib/apiError";

import type { PbxUser } from "./types";

export const SOFTPHONE_RELEASES = "https://github.com/optimiumnexusllc/nimbora/releases?q=softphone";
export const SOFTPHONE_DOWNLOADS = [
    { platform: "Windows", icon: Monitor, hint: ".msi ou .exe" },
    { platform: "macOS", icon: Laptop, hint: ".dmg (Intel + Apple Silicon)" },
    { platform: "Linux", icon: Monitor, hint: ".deb, .rpm ou .AppImage" },
    { platform: "Android", icon: Smartphone, hint: ".apk" },
    { platform: "iPhone / iPad", icon: Apple, hint: "TestFlight / App Store" },
    { platform: "Navigateur", icon: Globe, hint: "web, installable" },
];

type Activation = { code: string; expires_at: string; server: string; link: string; display_name: string; extension: string | null };

export function SoftphoneDialog({ user, onClose }: { user: PbxUser | null; onClose: () => void }) {
    const brand = useBrand();
    const [activation, setActivation] = useState<Activation | null>(null);
    const [qr, setQr] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        setActivation(null);
        setQr(null);
        setError(null);
        if (!user) return;
        void (async () => {
            const response = await createSoftphoneActivationApiV1PbxExtensionsUserUuidSoftphonePost({ path: { user_uuid: user.uuid } });
            if (response.error || !response.data) {
                setError(detailFromError(response.error, "Code impossible à créer"));
                return;
            }
            const data = response.data as unknown as Activation;
            setActivation(data);
            try {
                setQr(await QRCode.toDataURL(data.link, { margin: 1, width: 240, errorCorrectionLevel: "M" }));
            } catch {
                setQr(null);
            }
        })();
    }, [user]);

    useEffect(() => {
        if (!activation) return;
        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
    }, [activation]);

    const remaining = activation ? Math.max(0, Math.round((new Date(activation.expires_at).getTime() - now) / 1000)) : 0;
    const copy = (text: string, label: string) =>
        void navigator.clipboard?.writeText(text).then(
            () => toast.success(`${label} copié`),
            () => toast.error("Copie impossible"),
        );

    return (
        <Dialog open={user !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-2xl">
                <DialogHeader>
                    <DialogTitle>{brand.softphoneName} · {user?.name}</DialogTitle>
                    <DialogDescription>
                        Installez l&apos;application, puis scannez le QR code ou saisissez le code : l&apos;appareil devient le poste{" "}
                        {user?.extension ?? ""}, avec ses appels, ses collègues et sa messagerie.
                    </DialogDescription>
                </DialogHeader>
                {error ? (
                    <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm" data-testid="softphone-error">
                        {error}
                    </p>
                ) : !activation ? (
                    <div className="flex justify-center py-10">
                        <Loader2 className="animate-spin text-muted-foreground" />
                    </div>
                ) : (
                    <div className="grid gap-6 md:grid-cols-[240px_minmax(0,1fr)]" data-testid="softphone-activation">
                        <div className="space-y-2 text-center">
                            {qr ? (
                                // eslint-disable-next-line @next/next/no-img-element -- a generated data: URL
                                <img src={qr} alt="QR code d'activation" width={240} height={240} className="rounded-lg bg-white p-2" />
                            ) : (
                                <div className="flex size-60 items-center justify-center rounded-lg border text-sm text-muted-foreground">QR indisponible</div>
                            )}
                            <p className="text-xs text-muted-foreground">À scanner avec le téléphone (appareil photo).</p>
                        </div>
                        <div className="min-w-0 space-y-4">
                            <div>
                                <p className="text-sm text-muted-foreground">Code d&apos;activation</p>
                                <div className="flex items-center gap-2">
                                    <p className="font-mono text-3xl font-semibold tracking-[0.2em]" data-testid="softphone-code">
                                        {activation.code}
                                    </p>
                                    <Button variant="ghost" size="icon" aria-label="Copier le code" onClick={() => copy(activation.code, "Code")}>
                                        <Copy />
                                    </Button>
                                </div>
                                <p className={`text-xs ${remaining < 60 ? "text-amber-300" : "text-muted-foreground"}`}>
                                    {remaining > 0
                                        ? `Valable ${Math.floor(remaining / 60)} min ${String(remaining % 60).padStart(2, "0")} s, une seule fois`
                                        : "Code expiré : fermez et recommencez"}
                                </p>
                            </div>
                            {activation.server && (
                                <div className="min-w-0">
                                    <p className="text-sm text-muted-foreground">Adresse de la plateforme</p>
                                    <div className="flex items-center gap-2">
                                        <p className="truncate font-mono text-sm">{activation.server}</p>
                                        <Button variant="ghost" size="icon" aria-label="Copier l'adresse" onClick={() => copy(activation.server, "Adresse")}>
                                            <Copy />
                                        </Button>
                                    </div>
                                </div>
                            )}
                            <div>
                                <p className="mb-2 text-sm text-muted-foreground">Télécharger l&apos;application</p>
                                <div className="grid grid-cols-2 gap-2">
                                    {SOFTPHONE_DOWNLOADS.map(({ platform, icon: Icon, hint }) => (
                                        <a
                                            key={platform}
                                            href={SOFTPHONE_RELEASES}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="flex items-center gap-2 rounded-md border border-border/60 px-2 py-1.5 text-sm hover:bg-muted/40"
                                        >
                                            <Icon className="size-4 shrink-0" />
                                            <span className="min-w-0">
                                                <span className="block">{platform}</span>
                                                <span className="block text-xs leading-snug text-muted-foreground">{hint}</span>
                                            </span>
                                        </a>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                )}
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Fermer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

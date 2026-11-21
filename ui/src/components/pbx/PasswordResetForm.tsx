"use client";

import { CheckCircle2, KeyRound } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { resetPasswordApiV1PbxPasswordResetPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";

/** Page behind the PBX's password-reset e-mail (white label). */
export function PasswordResetForm() {
    const params = useSearchParams();
    const host = params.get("host") ?? "";
    const token = params.get("token") ?? "";
    const userUuid = params.get("user_uuid") ?? "";
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState(false);

    if (!host || !token || !userUuid) {
        return (
            <p className="text-sm text-muted-foreground" data-testid="invalid-link">
                Ce lien de réinitialisation est incomplet. Ouvrez-le directement depuis l&apos;e-mail reçu, ou
                demandez-en un nouveau à votre administrateur.
            </p>
        );
    }
    if (done) {
        return (
            <div className="space-y-2 text-center">
                <CheckCircle2 className="mx-auto size-10 text-emerald-400" />
                <h1 className="font-display text-xl font-semibold">Mot de passe modifié</h1>
                <p className="text-sm text-muted-foreground">
                    Vous pouvez vous reconnecter à votre téléphone ou à votre softphone avec le nouveau mot de passe.
                </p>
            </div>
        );
    }

    const tooShort = password.length > 0 && password.length < 8;
    const mismatch = confirm.length > 0 && confirm !== password;
    const submit = async (event: React.FormEvent) => {
        event.preventDefault();
        if (password.length < 8 || password !== confirm) return;
        setBusy(true);
        setError(null);
        const response = await resetPasswordApiV1PbxPasswordResetPost({
            body: { host, token, user_uuid: userUuid, password },
        });
        setBusy(false);
        if (response.error) {
            setError(detailFromError(response.error, "Réinitialisation impossible"));
            return;
        }
        setDone(true);
    };

    return (
        <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1">
                <h1 className="flex items-center gap-2 font-display text-xl font-semibold">
                    <KeyRound className="size-5" /> Nouveau mot de passe
                </h1>
                <p className="text-sm text-muted-foreground">Pour votre compte de téléphonie d&apos;entreprise.</p>
            </div>
            <div className="space-y-1">
                <Label htmlFor="pbx-password">Mot de passe (8 caractères minimum)</Label>
                <Input
                    id="pbx-password"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                />
                {tooShort && <p className="text-xs text-amber-400">Au moins 8 caractères.</p>}
            </div>
            <div className="space-y-1">
                <Label htmlFor="pbx-password-confirm">Confirmation</Label>
                <Input
                    id="pbx-password-confirm"
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                />
                {mismatch && <p className="text-xs text-amber-400">Les deux mots de passe diffèrent.</p>}
            </div>
            {error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy || password.length < 8 || password !== confirm}>
                Enregistrer le mot de passe
            </Button>
        </form>
    );
}

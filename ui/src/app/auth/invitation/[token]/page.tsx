"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    acceptInvitationApiV1AuthInvitationsTokenAcceptPost,
    readInvitationApiV1AuthInvitationsTokenGet,
} from "@/client/sdk.gen";
import type { InvitationInfo } from "@/client/types.gen";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";

/** Create one's account from an invitation link (or join with an existing one). */
export default function InvitationPage() {
    const { token } = useParams<{ token: string }>();
    const [invitation, setInvitation] = useState<InvitationInfo | null>(null);
    const [problem, setProblem] = useState<string | null>(null);
    const [name, setName] = useState("");
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        void readInvitationApiV1AuthInvitationsTokenGet({ path: { token } }).then((response) => {
            if (response.error || !response.data) {
                setProblem(detailFromError(response.error, "Invitation introuvable"));
                return;
            }
            setInvitation(response.data);
            setName(response.data.name ?? "");
        });
    }, [token]);

    const existing = invitation?.existing_account ?? false;
    const mismatch = !existing && confirm !== "" && confirm !== password;

    async function accept(e: React.FormEvent) {
        e.preventDefault();
        setLoading(true);
        const response = await acceptInvitationApiV1AuthInvitationsTokenAcceptPost({
            path: { token },
            body: { password, name: existing ? null : name || null },
        });
        if (response.error || !response.data) {
            setLoading(false);
            toast.error(detailFromError(response.error, "Invitation refusée"));
            return;
        }
        await fetch("/api/auth/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: response.data.token, user: response.data.user }),
        });
        window.location.href = invitation?.kind === "reseller_admin" ? "/reseller" : "/after-sign-in";
    }

    return (
        <AuthShell>
            <div className="space-y-1.5 text-center">
                <h1 className="text-2xl font-semibold tracking-tight">
                    {invitation ? `Rejoindre ${invitation.target_name || "la plateforme"}` : "Invitation"}
                </h1>
                <p className="text-sm text-muted-foreground">
                    {problem ??
                        (invitation
                            ? existing
                                ? `Un compte existe déjà pour ${invitation.email} : saisissez son mot de passe.`
                                : `Créez votre compte pour ${invitation.email}.`
                            : "Chargement…")}
                </p>
            </div>
            {invitation && (
                <form onSubmit={accept} className="space-y-4">
                    {!existing && (
                        <div className="space-y-2">
                            <Label htmlFor="name">Votre nom</Label>
                            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                        </div>
                    )}
                    <div className="space-y-2">
                        <Label htmlFor="password">{existing ? "Mot de passe" : "Choisissez un mot de passe"}</Label>
                        <Input
                            id="password"
                            type="password"
                            minLength={8}
                            required
                            autoComplete={existing ? "current-password" : "new-password"}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                        />
                    </div>
                    {!existing && (
                        <div className="space-y-2">
                            <Label htmlFor="confirm">Confirmez le mot de passe</Label>
                            <Input
                                id="confirm"
                                type="password"
                                required
                                autoComplete="new-password"
                                value={confirm}
                                onChange={(e) => setConfirm(e.target.value)}
                            />
                            {mismatch && <p className="text-xs text-destructive">Les deux mots de passe diffèrent.</p>}
                        </div>
                    )}
                    <Button type="submit" className="w-full" disabled={loading || password.length < 8 || mismatch || (!existing && !confirm)}>
                        {existing ? "Rejoindre" : "Créer mon compte"}
                    </Button>
                </form>
            )}
        </AuthShell>
    );
}

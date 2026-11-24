"use client";

import { Plus, UserPlus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    adminCreateResellerApiV1SaasAdminResellersPost,
    adminInviteResellerAdminApiV1SaasAdminResellersResellerIdInvitationsPost,
    adminListResellersApiV1SaasAdminResellersGet,
    adminUpdateResellerApiV1SaasAdminResellersResellerIdPatch,
} from "@/client/sdk.gen";
import type { ResellerResponse } from "@/client/types.gen";
import { PageLayout, PageSection } from "@/components/layout/PageLayout";
import { InvitationLinkDialog } from "@/components/saas/InvitationLinkDialog";
import { Badge } from "@/components/ui/badge";
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
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

const EMPTY = { name: "", contact_email: "", commission_percent: "20", admin_email: "", admin_name: "" };

/** The platform's resellers: commission, status, administrators' links. */
export default function ResellersAdminPage() {
    const { user, loading: authLoading } = useAuth();
    const hasFetched = useRef(false);
    const [resellers, setResellers] = useState<ResellerResponse[]>([]);
    const [form, setForm] = useState<typeof EMPTY | null>(null);
    const [link, setLink] = useState<string | null>(null);
    const [invite, setInvite] = useState<{ id: number; email: string } | null>(null);

    const load = useCallback(async () => {
        const response = await adminListResellersApiV1SaasAdminResellersGet();
        if (response.error) {
            toast.error(detailFromError(response.error, "Revendeurs indisponibles"));
            return;
        }
        setResellers(response.data ?? []);
    }, []);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void load();
    }, [authLoading, user, load]);

    async function create() {
        if (!form) return;
        const response = await adminCreateResellerApiV1SaasAdminResellersPost({
            body: {
                name: form.name,
                contact_email: form.contact_email || null,
                commission_percent: Number(form.commission_percent.replace(",", ".")),
                admin_email: form.admin_email,
                admin_name: form.admin_name || null,
            },
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Revendeur non créé"));
            return;
        }
        setForm(null);
        setLink(response.data.invitation_url);
        void load();
    }

    async function update(id: number, body: { commission_percent?: number; is_active?: boolean }) {
        const response = await adminUpdateResellerApiV1SaasAdminResellersResellerIdPatch({ path: { reseller_id: id }, body });
        if (response.error) {
            toast.error(detailFromError(response.error, "Modification impossible"));
            return;
        }
        void load();
    }

    async function sendInvite() {
        if (!invite) return;
        const response = await adminInviteResellerAdminApiV1SaasAdminResellersResellerIdInvitationsPost({
            path: { reseller_id: invite.id },
            body: { email: invite.email },
        });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Lien non créé"));
            return;
        }
        setInvite(null);
        setLink(response.data.invitation_url);
    }

    return (
        <PageLayout
            title="Revendeurs"
            description="Un seul niveau : la plateforme, ses revendeurs, leurs entreprises. La commission est prélevée sur chaque paiement de leurs clients."
        >
            <PageSection
                title="Revendeurs"
                actions={
                    <Button type="button" onClick={() => setForm({ ...EMPTY })}>
                        <Plus /> Nouveau revendeur
                    </Button>
                }
            >
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Revendeur</TableHead>
                            <TableHead>Entreprises</TableHead>
                            <TableHead>Commission (%)</TableHead>
                            <TableHead>Paiement en ligne</TableHead>
                            <TableHead>Actif</TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {resellers.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center text-muted-foreground">
                                    Aucun revendeur pour l&apos;instant.
                                </TableCell>
                            </TableRow>
                        )}
                        {resellers.map((r) => (
                            <TableRow key={r.id}>
                                <TableCell>
                                    <div className="font-medium">{r.name}</div>
                                    <div className="text-xs text-muted-foreground">{r.contact_email ?? ""}</div>
                                </TableCell>
                                <TableCell>{r.companies}</TableCell>
                                <TableCell>
                                    <Input
                                        aria-label={`Commission de ${r.name}`}
                                        className="w-24"
                                        defaultValue={String(r.commission_percent)}
                                        inputMode="decimal"
                                        onBlur={(e) => {
                                            const value = Number(e.target.value.replace(",", "."));
                                            if (!Number.isNaN(value) && value !== r.commission_percent) void update(r.id, { commission_percent: value });
                                        }}
                                    />
                                </TableCell>
                                <TableCell>
                                    <Badge variant={r.stripe_ready ? "secondary" : "outline"}>{r.stripe_ready ? "Actif" : "À connecter"}</Badge>
                                </TableCell>
                                <TableCell>
                                    <Switch
                                        aria-label={`${r.name} actif`}
                                        checked={r.is_active}
                                        onCheckedChange={(is_active) => void update(r.id, { is_active })}
                                    />
                                </TableCell>
                                <TableCell className="text-right">
                                    <Button type="button" variant="ghost" size="sm" onClick={() => setInvite({ id: r.id, email: "" })}>
                                        <UserPlus /> Administrateur
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </PageSection>

            <Dialog open={form !== null} onOpenChange={(open) => !open && setForm(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Nouveau revendeur</DialogTitle>
                        <DialogDescription>Son premier administrateur reçoit un lien pour créer son compte.</DialogDescription>
                    </DialogHeader>
                    {form && (
                        <div className="grid gap-3">
                            <div className="space-y-1">
                                <Label htmlFor="r-name">Nom</Label>
                                <Input id="r-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1">
                                    <Label htmlFor="r-contact">E-mail de contact</Label>
                                    <Input id="r-contact" type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="r-commission">Commission (%)</Label>
                                    <Input id="r-commission" inputMode="decimal" value={form.commission_percent} onChange={(e) => setForm({ ...form, commission_percent: e.target.value })} />
                                </div>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1">
                                    <Label htmlFor="r-admin">E-mail de l&apos;administrateur</Label>
                                    <Input id="r-admin" type="email" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="r-admin-name">Nom (facultatif)</Label>
                                    <Input id="r-admin-name" value={form.admin_name} onChange={(e) => setForm({ ...form, admin_name: e.target.value })} />
                                </div>
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => setForm(null)}>
                            Annuler
                        </Button>
                        <Button type="button" onClick={() => void create()} disabled={!form?.name.trim() || !form?.admin_email.trim()}>
                            Créer et obtenir le lien
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={invite !== null} onOpenChange={(open) => !open && setInvite(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Inviter un administrateur</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-1">
                        <Label htmlFor="invite-email">E-mail</Label>
                        <Input id="invite-email" type="email" value={invite?.email ?? ""} onChange={(e) => invite && setInvite({ ...invite, email: e.target.value })} />
                    </div>
                    <DialogFooter>
                        <Button type="button" onClick={() => void sendInvite()} disabled={!invite?.email.trim()}>
                            Obtenir le lien
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <InvitationLinkDialog url={link} title="Lien de l'administrateur" onClose={() => setLink(null)} />
        </PageLayout>
    );
}

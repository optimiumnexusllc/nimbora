"use client";

import { FileUp, KeyRound, PhoneForwarded, Plus, Smartphone, Trash2, UserPlus } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
    createExtensionApiV1PbxExtensionsPost,
    deleteExtensionApiV1PbxExtensionsUserUuidDelete,
    extensionPasswordResetApiV1PbxExtensionsPasswordResetPost,
    previewImportApiV1PbxExtensionsImportPreviewPost,
    runImportApiV1PbxExtensionsImportPost,
} from "@/client/sdk.gen";
import type { ExtensionResponse, ImportRow } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

import { CredentialsDialog } from "./CredentialsDialog";
import { PresenceBadge, useTeamPresence } from "./Presence";
import type { PbxUser } from "./types";

const TEMPLATE_CSV = "prenom;nom;poste;email;ligne;messagerie;agent\nAwa;Diallo;1010;awa@exemple.ci;navigateur;oui;oui\n";

type Form = {
    firstname: string;
    lastname: string;
    extension: string;
    email: string;
    line: "sip" | "webrtc";
    voicemail: boolean;
    agent: boolean;
};
const EMPTY: Form = { firstname: "", lastname: "", extension: "", email: "", line: "webrtc", voicemail: true, agent: false };

export function ExtensionsTab({
    users,
    error,
    onChanged,
    onCallSettings,
    onSoftphone,
}: {
    users: PbxUser[];
    error?: string;
    onChanged: () => void;
    onCallSettings?: (user: PbxUser) => void;
    onSoftphone?: (user: PbxUser) => void;
}) {
    const presence = useTeamPresence();
    const [creating, setCreating] = useState(false);
    const [form, setForm] = useState<Form>(EMPTY);
    const [busy, setBusy] = useState(false);
    const [credentials, setCredentials] = useState<{ items: ExtensionResponse[]; csv?: string }>({ items: [] });
    const [importing, setImporting] = useState(false);
    const [csv, setCsv] = useState("");
    const [preview, setPreview] = useState<ImportRow[] | null>(null);
    const fileInput = useRef<HTMLInputElement>(null);
    const [fileName, setFileName] = useState<string | null>(null);

    const create = async () => {
        setBusy(true);
        const response = await createExtensionApiV1PbxExtensionsPost({
            body: { ...form, email: form.email.trim() || null },
        });
        setBusy(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Création impossible"));
            return;
        }
        setCreating(false);
        setForm(EMPTY);
        setCredentials({ items: [response.data] });
        onChanged();
    };

    const loadPreview = async (content: string) => {
        setCsv(content);
        if (!content.trim()) {
            setPreview(null);
            return;
        }
        const response = await previewImportApiV1PbxExtensionsImportPreviewPost({ body: { content } });
        if (response.error) {
            toast.error(detailFromError(response.error, "Fichier illisible"));
            return;
        }
        setPreview(response.data ?? []);
    };

    const runImport = async () => {
        setBusy(true);
        const response = await runImportApiV1PbxExtensionsImportPost({ body: { content: csv } });
        setBusy(false);
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Import impossible"));
            return;
        }
        const { created, failed, credentials_csv } = response.data;
        setImporting(false);
        setCsv("");
        setPreview(null);
        setFileName(null);
        if (failed.length) toast.error(`${failed.length} ligne(s) non importée(s) : corrigez-les et réimportez-les.`);
        if (created.length) setCredentials({ items: created, csv: credentials_csv });
        onChanged();
    };

    const valid = preview?.filter((r) => r.errors.length === 0).length ?? 0;

    return (
        <PageSection
            title="Postes et utilisateurs"
            actions={
                <>
                    <Button variant="outline" onClick={() => setImporting(true)}>
                        <FileUp /> Importer (CSV)
                    </Button>
                    <Button onClick={() => setCreating(true)}>
                        <UserPlus /> Nouveau poste
                    </Button>
                </>
            }
        >
            {error && <p className="mb-3 text-sm text-amber-400">Indisponible pour le moment : {error}</p>}
            {users.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Aucun poste.</p>
            ) : (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Utilisateur</TableHead>
                            <TableHead>Poste</TableHead>
                            <TableHead>Présence</TableHead>
                            <TableHead>E-mail</TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {users.map((u) => (
                            <TableRow key={u.uuid} data-testid="pbx-user">
                                <TableCell className="font-medium">{u.name}</TableCell>
                                <TableCell className="font-mono">{u.extension ?? "—"}</TableCell>
                                <TableCell>
                                    <PresenceBadge presence={u.extension ? presence?.extensions[u.extension] : undefined} />
                                </TableCell>
                                <TableCell className="text-sm text-muted-foreground">{u.email ?? "—"}</TableCell>
                                <TableCell className="space-x-1 text-right">
                                    {onSoftphone && (
                                        <Button variant="ghost" size="sm" aria-label={`Softphone de ${u.name}`} onClick={() => onSoftphone(u)}>
                                            <Smartphone /> Softphone
                                        </Button>
                                    )}
                                    {onCallSettings && u.id != null && (
                                        <Button variant="ghost" size="sm" aria-label={`Renvois de ${u.name}`} onClick={() => onCallSettings(u)}>
                                            <PhoneForwarded /> Renvois
                                        </Button>
                                    )}
                                    {(u.login || u.email) && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={async () => {
                                                const response = await extensionPasswordResetApiV1PbxExtensionsPasswordResetPost({
                                                    body: { login: (u.login || u.email) as string },
                                                });
                                                if (response.error) toast.error(detailFromError(response.error, "Envoi impossible"));
                                                else toast.success(`Lien de mot de passe envoyé à ${u.email ?? u.login}`);
                                            }}
                                        >
                                            <KeyRound /> Mot de passe
                                        </Button>
                                    )}
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="text-destructive"
                                        aria-label={`Supprimer ${u.name}`}
                                        onClick={async () => {
                                            if (!window.confirm(`Supprimer ${u.name}, sa ligne, son poste et sa messagerie ?`)) return;
                                            const response = await deleteExtensionApiV1PbxExtensionsUserUuidDelete({ path: { user_uuid: u.uuid } });
                                            if (response.error) toast.error(detailFromError(response.error, "Suppression impossible"));
                                            else {
                                                toast.success("Poste supprimé");
                                                onChanged();
                                            }
                                        }}
                                    >
                                        <Trash2 />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}

            <Dialog open={creating} onOpenChange={setCreating}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Nouveau poste</DialogTitle>
                        <DialogDescription>
                            Utilisateur, ligne, numéro de poste, compte SIP, messagerie et accès, en une fois.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1">
                            <Label htmlFor="ext-first">Prénom</Label>
                            <Input id="ext-first" value={form.firstname} onChange={(e) => setForm({ ...form, firstname: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="ext-last">Nom</Label>
                            <Input id="ext-last" value={form.lastname} onChange={(e) => setForm({ ...form, lastname: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="ext-number">Numéro de poste</Label>
                            <Input id="ext-number" inputMode="numeric" placeholder="1010" value={form.extension} onChange={(e) => setForm({ ...form, extension: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="ext-email">E-mail (identifiant, messagerie)</Label>
                            <Input id="ext-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                        </div>
                        <div className="space-y-1 sm:col-span-2">
                            <Label>Téléphone</Label>
                            <Select value={form.line} onValueChange={(v) => setForm({ ...form, line: v as Form["line"] })}>
                                <SelectTrigger aria-label="Type de ligne" className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="webrtc">Softphone dans le navigateur</SelectItem>
                                    <SelectItem value="sip">Téléphone de bureau ou application SIP</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <label className="flex items-center gap-2 text-sm">
                            <Switch checked={form.voicemail} onCheckedChange={(v) => setForm({ ...form, voicemail: v })} aria-label="Messagerie vocale" />
                            Messagerie vocale
                        </label>
                        <label className="flex items-center gap-2 text-sm">
                            <Switch checked={form.agent} onCheckedChange={(v) => setForm({ ...form, agent: v })} aria-label="Agent du centre d'appels" />
                            Agent du centre d&apos;appels
                        </label>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreating(false)}>
                            Annuler
                        </Button>
                        <Button onClick={create} disabled={busy || !form.firstname.trim() || !form.extension.trim()}>
                            <Plus /> Créer le poste
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={importing} onOpenChange={setImporting}>
                <DialogContent className="sm:max-w-3xl">
                    <DialogHeader className="min-w-0">
                        <DialogTitle>Importer des postes</DialogTitle>
                        <DialogDescription>
                            Colonnes : prenom, nom, poste, email, ligne (navigateur ou sip), messagerie (oui/non), agent
                            (oui/non). Séparateur virgule ou point-virgule, 500 lignes au maximum.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="min-w-0 space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <input
                                ref={fileInput}
                                type="file"
                                accept=".csv,text/csv"
                                className="hidden"
                                data-testid="csv-input"
                                onChange={async (e) => {
                                    const file = e.target.files?.[0];
                                    if (!file) return;
                                    setFileName(file.name);
                                    await loadPreview(await file.text());
                                }}
                            />
                            <Button variant="outline" onClick={() => fileInput.current?.click()}>
                                <FileUp /> Choisir un fichier
                            </Button>
                            {fileName && <span className="text-sm text-muted-foreground">{fileName}</span>}
                            <Button variant="ghost" size="sm" onClick={() => void loadPreview(TEMPLATE_CSV)}>
                                Voir un exemple
                            </Button>
                        </div>
                        <Textarea
                            aria-label="Contenu CSV"
                            rows={4}
                            className="font-mono text-xs"
                            placeholder="…ou collez le contenu ici"
                            value={csv}
                            onChange={(e) => setCsv(e.target.value)}
                            onBlur={() => void loadPreview(csv)}
                        />
                        {preview && (
                            <div className="max-h-64 overflow-auto rounded-md border border-border/60">
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Ligne</TableHead>
                                            <TableHead>Personne</TableHead>
                                            <TableHead>Poste</TableHead>
                                            <TableHead>Type</TableHead>
                                            <TableHead>Contrôle</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {preview.map((row) => (
                                            <TableRow key={row.line} data-testid="import-row">
                                                <TableCell className="text-xs text-muted-foreground">{row.line}</TableCell>
                                                <TableCell>
                                                    {row.firstname} {row.lastname}
                                                </TableCell>
                                                <TableCell className="font-mono">{row.extension}</TableCell>
                                                <TableCell className="text-xs">
                                                    {row.type === "webrtc" ? "Navigateur" : "SIP"}
                                                    {row.voicemail && " · messagerie"}
                                                    {row.agent && " · agent"}
                                                </TableCell>
                                                <TableCell>
                                                    {row.errors.length ? (
                                                        <span className="text-xs text-red-300">{row.errors.join(" ; ")}</span>
                                                    ) : (
                                                        <Badge variant="secondary">OK</Badge>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setImporting(false)}>
                            Annuler
                        </Button>
                        <Button onClick={runImport} disabled={busy || valid === 0}>
                            Créer {valid} poste{valid > 1 ? "s" : ""}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <CredentialsDialog items={credentials.items} csv={credentials.csv} onClose={() => setCredentials({ items: [] })} />
        </PageSection>
    );
}

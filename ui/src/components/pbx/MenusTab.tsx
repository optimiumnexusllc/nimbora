"use client";

import { Bot, CircleAlert, CircleCheck, CircleDashed, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
    createMenuApiV1PbxMenusPost,
    deleteMenuApiV1PbxMenusMenuIdDelete,
    publishMenuApiV1PbxMenusMenuIdPublishPost,
    updateMenuApiV1PbxMenusMenuIdPut,
} from "@/client/sdk.gen";
import type { MenuSpec } from "@/client/types.gen";
import { PageSection } from "@/components/layout/PageLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";

import { describeDestination,type Destination, type DestinationSources } from "./DestinationPicker";
import { EMPTY_SPEC, MenuEditor, spokenMenu } from "./MenuEditor";
import type { MenuSpecShape, PbxMenu } from "./types";

const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";

function Status({ menu }: { menu: PbxMenu }) {
    if (menu.last_error)
        return (
            <Badge variant="outline" className="gap-1 border-red-500/50 text-red-300">
                <CircleAlert className="size-3" /> Échec de publication
            </Badge>
        );
    if (!menu.published_at)
        return (
            <Badge variant="outline" className="gap-1">
                <CircleDashed className="size-3" /> Brouillon
            </Badge>
        );
    if (!menu.up_to_date)
        return (
            <Badge variant="outline" className="gap-1 border-amber-500/50 text-amber-300">
                <CircleAlert className="size-3" /> Modifié, à republier
            </Badge>
        );
    return (
        <Badge variant="outline" className="gap-1 border-emerald-500/50 text-emerald-300">
            <CircleCheck className="size-3" /> Publié
        </Badge>
    );
}

export function MenusTab({
    menus,
    sources,
    onChanged,
}: {
    menus: PbxMenu[];
    sources: DestinationSources;
    onChanged: () => void;
}) {
    const [editing, setEditing] = useState<{ id?: number; name: string; spec: MenuSpecShape } | null>(null);
    const [busy, setBusy] = useState<number | null>(null);

    const publish = async (id: number) => {
        setBusy(id);
        const response = await publishMenuApiV1PbxMenusMenuIdPublishPost({ path: { menu_id: id } });
        setBusy(null);
        onChanged();
        if (response.error) {
            toast.error(detailFromError(response.error, "Publication impossible"));
            return false;
        }
        toast.success("Menu publié sur le PBX");
        return true;
    };

    const save = async (name: string, spec: MenuSpecShape, andPublish: boolean) => {
        const body = { name, spec: spec as unknown as MenuSpec };
        const response = editing?.id
            ? await updateMenuApiV1PbxMenusMenuIdPut({ path: { menu_id: editing.id }, body })
            : await createMenuApiV1PbxMenusPost({ body });
        if (response.error || !response.data) {
            toast.error(detailFromError(response.error, "Enregistrement impossible"));
            return false;
        }
        const id = (response.data as unknown as PbxMenu).id;
        if (andPublish) {
            await publish(id);
        } else {
            toast.success("Brouillon enregistré");
            onChanged();
        }
        return true;
    };

    return (
        <PageSection
            title="Serveurs vocaux"
            description="« Pour le service commercial, tapez 1 » — des menus dessinés ici, prononcés avec votre voix, et une touche pour parler à un agent IA."
            actions={
                <Button onClick={() => setEditing({ name: "", spec: EMPTY_SPEC })}>
                    <Plus /> Nouveau menu
                </Button>
            }
        >
            {menus.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                    Aucun serveur vocal. Créez un menu, publiez-le, puis faites-y arriver un numéro (onglet Numéros).
                </p>
            ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                    {menus.map((menu) => {
                        const ai = menu.spec.choices.filter((c) => c.type === "ai").length + (menu.spec.fallback?.type === "ai" ? 1 : 0);
                        return (
                            <div key={menu.id} className="card-weave flex min-w-0 flex-col gap-3 rounded-xl border border-border/60 p-4" data-testid="pbx-menu">
                                <div className="flex min-w-0 items-start gap-2">
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate font-medium">{menu.name}</p>
                                        <p className="line-clamp-2 text-sm italic text-muted-foreground">« {spokenMenu(menu.spec)} »</p>
                                    </div>
                                    <Status menu={menu} />
                                </div>
                                <ul className="space-y-1 text-sm">
                                    {menu.spec.choices.map((c) => (
                                        <li key={c.digit} className="flex min-w-0 items-center gap-2">
                                            <Badge variant="outline" className="font-mono">
                                                {c.digit}
                                            </Badge>
                                            <span className="truncate">{c.label}</span>
                                            <span className="ml-auto flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                                                {c.type === "ai" && <Bot className="size-3.5 text-brand-cyan" />}
                                                {describeDestination(c as Destination, sources)}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                                {menu.last_error && <p className="break-words text-xs text-red-300">{menu.last_error}</p>}
                                <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-border/40 pt-3">
                                    <span className="mr-auto text-xs text-muted-foreground">
                                        {ai > 0 && (
                                            <span className="mr-2 inline-flex items-center gap-1 text-brand-cyan">
                                                <Bot className="size-3.5" /> {ai} accès IA
                                            </span>
                                        )}
                                        {menu.published_at && `Publié le ${fmt(menu.published_at)}`}
                                    </span>
                                    <Button variant="ghost" size="sm" onClick={() => setEditing({ id: menu.id, name: menu.name, spec: menu.spec })}>
                                        <Pencil /> Modifier
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        disabled={busy === menu.id || menu.up_to_date}
                                        onClick={() => void publish(menu.id)}
                                    >
                                        <Send /> {busy === menu.id ? "Publication…" : "Publier"}
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="text-destructive"
                                        aria-label={`Supprimer ${menu.name}`}
                                        onClick={async () => {
                                            if (!window.confirm(`Supprimer le menu « ${menu.name} » (et ses messages sur le PBX) ?`)) return;
                                            const response = await deleteMenuApiV1PbxMenusMenuIdDelete({ path: { menu_id: menu.id } });
                                            if (response.error) {
                                                toast.error(detailFromError(response.error, "Suppression impossible"));
                                                return;
                                            }
                                            toast.success("Menu supprimé");
                                            onChanged();
                                        }}
                                    >
                                        <Trash2 />
                                    </Button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
            {editing && (
                <MenuEditor
                    key={editing.id ?? "new"}
                    open
                    onOpenChange={(open) => !open && setEditing(null)}
                    initial={{ name: editing.name, spec: editing.spec }}
                    menuId={editing.id}
                    sources={sources}
                    onSave={save}
                />
            )}
        </PageSection>
    );
}

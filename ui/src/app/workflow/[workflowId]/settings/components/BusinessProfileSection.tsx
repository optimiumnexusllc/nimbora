"use client";

import { Store } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useUnsavedChanges } from "@/context/UnsavedChangesContext";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

export function BusinessProfileSection({
    workflowConfigurations,
    onSave,
}: {
    workflowConfigurations: WorkflowConfigurations;
    onSave: (value: WorkflowConfigurations) => Promise<void>;
}) {
    const saved = workflowConfigurations.use_business_profile !== false;
    const [enabled, setEnabled] = useState(saved);
    const [saving, setSaving] = useState(false);
    useEffect(() => setEnabled(saved), [saved]);
    const dirty = enabled !== saved;
    useUnsavedChanges("business-profile", dirty);

    const save = async () => {
        setSaving(true);
        try {
            await onSave({ ...workflowConfigurations, use_business_profile: enabled });
            toast.success("Réglage enregistré. Publiez l'agent pour l'appliquer aux nouveaux échanges.");
        } catch {
            toast.error("Enregistrement impossible");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Card id="business-profile">
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Store className="h-4 w-4" />
                    Fiche entreprise
                </CardTitle>
                <CardDescription>
                    Identité, horaires, offres, FAQ et compétences communes définies dans{" "}
                    <Link href="/business" className="underline">
                        Mon entreprise
                    </Link>
                    , ajoutées au prompt de cet agent. Désactivez-la pour un agent qui ne représente pas
                    l&apos;entreprise (tests, enquêtes…).
                </CardDescription>
            </CardHeader>
            <CardContent>
                <div className="flex items-center gap-3">
                    <Switch id="use-business-profile" checked={enabled} onCheckedChange={setEnabled} />
                    <Label htmlFor="use-business-profile">Utiliser la fiche entreprise</Label>
                </div>
            </CardContent>
            <CardFooter className="border-t pt-6">
                <Button onClick={save} disabled={!dirty || saving}>
                    Enregistrer
                </Button>
            </CardFooter>
        </Card>
    );
}

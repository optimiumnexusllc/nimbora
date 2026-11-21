"use client";

import { PhoneForwarded } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { setNumberDestinationApiV1PbxNumbersPut } from "@/client/sdk.gen";
import type { MenuAction } from "@/client/types.gen";
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
import { detailFromError } from "@/lib/apiError";

import { type Destination, DestinationPicker,type DestinationSources } from "./DestinationPicker";

export type NumberEdit = { number: string; destination: Destination; existing: boolean };

export function NumberDialog({
    edit,
    onClose,
    sources,
    onDone,
}: {
    edit: NumberEdit | null;
    onClose: () => void;
    sources: DestinationSources;
    onDone: () => void;
}) {
    const [number, setNumber] = useState("");
    const [destination, setDestination] = useState<Destination>({ type: "hangup", target_id: null });
    const [saving, setSaving] = useState(false);
    useEffect(() => {
        if (!edit) return;
        setNumber(edit.number);
        setDestination(edit.destination);
    }, [edit]);
    const ready = number.trim() && (destination.type === "hangup" || destination.target_id != null);
    return (
        <Dialog open={edit !== null} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle>{edit?.existing ? `Destination du ${edit.number}` : "Ajouter un numéro"}</DialogTitle>
                    <DialogDescription>
                        Où sonnent les appels reçus sur ce numéro : un agent IA, un serveur vocal, une file, un poste ou une
                        messagerie. Les horaires et réglages existants du numéro sont conservés.
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    <div className="space-y-1">
                        <Label htmlFor="number-value">Numéro</Label>
                        <Input
                            id="number-value"
                            placeholder="+225 27 00 00 00 99"
                            value={number}
                            disabled={edit?.existing}
                            onChange={(e) => setNumber(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <Label>Destination</Label>
                        <DestinationPicker label="Destination du numéro" value={destination} sources={sources} onChange={setDestination} />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Annuler
                    </Button>
                    <Button
                        disabled={!ready || saving}
                        onClick={async () => {
                            setSaving(true);
                            const response = await setNumberDestinationApiV1PbxNumbersPut({
                                body: { number: number.trim(), destination: destination as MenuAction },
                            });
                            setSaving(false);
                            if (response.error) {
                                toast.error(detailFromError(response.error, "Enregistrement impossible"));
                                return;
                            }
                            toast.success(`Le ${number.trim()} est routé`);
                            onClose();
                            onDone();
                        }}
                    >
                        <PhoneForwarded /> Enregistrer
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

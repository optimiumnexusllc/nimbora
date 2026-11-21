import { Suspense } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { PasswordResetForm } from "@/components/pbx/PasswordResetForm";

export default function PbxPasswordPage() {
    return (
        <AuthShell>
            <Suspense>
                <PasswordResetForm />
            </Suspense>
        </AuthShell>
    );
}

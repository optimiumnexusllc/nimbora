import { detailFromError } from "@/lib/apiError";

// The API answers in English; the sign-in pages speak French.
const FRENCH: Record<string, string> = {
    "Invalid email or password": "E-mail ou mot de passe incorrect.",
    "Email already registered": "Un compte existe déjà avec cet e-mail. Connectez-vous.",
    "Signup is disabled": "Les inscriptions sont fermées sur cette plateforme.",
};

export function authErrorMessage(error: unknown, fallback: string): string {
    const detail = detailFromError(error, fallback);
    if (FRENCH[detail]) return FRENCH[detail];
    if (/at least 8 characters/i.test(detail)) return "Le mot de passe doit contenir au moins 8 caractères.";
    if (/valid email/i.test(detail)) return "Adresse e-mail invalide.";
    return detail;
}

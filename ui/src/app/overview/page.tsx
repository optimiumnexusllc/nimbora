"use client";

import {
    ArrowRight,
    AudioLines,
    Bot,
    Brain,
    Headphones,
    type LucideIcon,
    Megaphone,
    Phone,
    ReceiptText,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/BrandLogo";
import { PageShell } from "@/components/layout/PageShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useAuth } from "@/lib/auth";
import { enterpriseApi, formatLimit, STATUS_LABELS, type Subscription } from "@/lib/enterpriseApi";

type QuickAction = {
    title: string;
    description: string;
    href: string;
    icon: LucideIcon;
    accent: string;
};

const ACTIONS: QuickAction[] = [
    {
        title: "Agents vocaux IA",
        description: "Concevez vos agents dans l'éditeur visuel et testez-les en un clic.",
        href: "/workflow",
        icon: Bot,
        accent: "from-brand-cyan to-brand-violet",
    },
    {
        title: "Centre d'appels",
        description: "Files d'attente, postes d'agents et softphone dans le navigateur.",
        href: "/contact-center",
        icon: Headphones,
        accent: "from-brand-violet to-brand-magenta",
    },
    {
        title: "Téléphonie",
        description: "Numéros, trunks SIP et routage des appels entrants.",
        href: "/telephony-configurations",
        icon: Phone,
        accent: "from-brand-mint to-brand-cyan",
    },
    {
        title: "Modèles d'IA",
        description: "LLM, reconnaissance et synthèse vocales, langues et voix.",
        href: "/model-configurations",
        icon: Brain,
        accent: "from-brand-cyan to-brand-mint",
    },
    {
        title: "Campagnes",
        description: "Appels sortants en masse, planifiés et suivis en temps réel.",
        href: "/campaigns",
        icon: Megaphone,
        accent: "from-brand-magenta to-brand-violet",
    },
    {
        title: "Enregistrements",
        description: "Écoutez, analysez et exportez les conversations.",
        href: "/recordings",
        icon: AudioLines,
        accent: "from-brand-violet to-brand-cyan",
    },
];

function HeroWave() {
    return (
        <div aria-hidden className="pointer-events-none flex h-20 items-center gap-[5px]">
            {Array.from({ length: 36 }).map((_, i) => (
                <span
                    key={i}
                    className="hero-wave-bar w-[3px] rounded-full bg-gradient-to-t from-brand-cyan via-brand-violet to-brand-magenta"
                    style={{
                        height: `${20 + Math.abs(Math.sin(i * 0.55) * Math.cos(i * 0.17)) * 80}%`,
                        animationDelay: `${(i % 9) * 0.11}s`,
                    }}
                />
            ))}
        </div>
    );
}

function UsageCard({ subscription }: { subscription: Subscription }) {
    const included = subscription.included_minutes;
    const pct = included ? Math.min(100, (subscription.used_minutes / included) * 100) : 0;
    return (
        <Card>
            <CardContent className="space-y-4 pt-6">
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-xs uppercase tracking-widest text-muted-foreground">Offre</p>
                        <p className="font-display text-xl font-bold">{subscription.plan_name}</p>
                    </div>
                    <span className="rounded-full border border-border px-3 py-1 text-xs">
                        {STATUS_LABELS[subscription.status]}
                    </span>
                </div>
                <div>
                    <div className="mb-2 flex items-baseline justify-between">
                        <span className="text-sm text-muted-foreground">Minutes ce mois-ci</span>
                        <span className="font-display text-2xl font-bold">
                            <span className="text-gradient">{Math.round(subscription.used_minutes).toLocaleString("fr-FR")}</span>
                            <span className="text-sm font-normal text-muted-foreground"> / {formatLimit(included)}</span>
                        </span>
                    </div>
                    {included !== null && <Progress value={pct} />}
                </div>
                <Button asChild variant="outline" className="w-full">
                    <Link href="/subscription">
                        <ReceiptText /> Gérer mon abonnement
                    </Link>
                </Button>
            </CardContent>
        </Card>
    );
}

export default function OverviewPage() {
    const { user, loading } = useAuth();
    const [subscription, setSubscription] = useState<Subscription | null>(null);
    const fetched = useRef(false);

    useEffect(() => {
        if (loading || !user || fetched.current) return;
        fetched.current = true;
        // Only present on SaaS deployments; silently absent otherwise.
        enterpriseApi.getSubscription().then(setSubscription).catch(() => undefined);
    }, [loading, user]);

    const firstName = user && "displayName" in user && typeof user.displayName === "string"
        ? user.displayName.split(" ")[0]
        : null;

    return (
        <PageShell>
            {/* Hero */}
            <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-[#060814] p-8 text-white shadow-2xl shadow-black/30 md:p-10">
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0"
                    style={{
                        background:
                            "radial-gradient(50% 70% at 90% 0%, rgb(124 92 255 / 0.5), transparent 70%), radial-gradient(40% 60% at 0% 100%, rgb(34 229 255 / 0.25), transparent 70%)",
                    }}
                />
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                    src="/brand/auth-hero.svg"
                    alt=""
                    aria-hidden
                    className="float-slow pointer-events-none absolute -right-24 -top-24 hidden w-[460px] opacity-70 md:block"
                />
                <div className="relative max-w-2xl space-y-5">
                    <div className="flex items-center gap-3">
                        <BrandMark className="h-10 w-10" />
                        <span className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300/80">
                            Tableau de bord
                        </span>
                    </div>
                    <h1 className="font-display text-3xl font-bold leading-tight tracking-tight md:text-5xl">
                        {firstName ? `Bonjour ${firstName}, ` : "Bienvenue, "}
                        <span className="text-gradient">vos agents sont prêts.</span>
                    </h1>
                    <p className="max-w-xl text-slate-300">
                        Créez un agent vocal, branchez un numéro et laissez l&apos;IA décrocher. Vos équipes
                        reprennent la main quand il le faut.
                    </p>
                    <div className="flex flex-wrap gap-3">
                        <Button asChild size="lg">
                            <Link href="/workflow">
                                Créer un agent <ArrowRight />
                            </Link>
                        </Button>
                        <Button
                            asChild
                            size="lg"
                            variant="outline"
                            className="border-white/20 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                        >
                            <Link href="/contact-center">Ouvrir le centre d&apos;appels</Link>
                        </Button>
                    </div>
                </div>
                <div className="relative mt-8 opacity-80">
                    <HeroWave />
                </div>
            </section>

            <div className="page-enter mt-8 grid gap-6 lg:grid-cols-[1fr_320px]">
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {ACTIONS.map((action) => {
                        const Icon = action.icon;
                        return (
                            <Link key={action.href} href={action.href} className="group">
                                <Card className="h-full transition-transform duration-300 group-hover:-translate-y-1">
                                    <CardContent className="space-y-3 pt-6">
                                        <div
                                            className={`inline-flex size-11 items-center justify-center rounded-xl bg-gradient-to-br ${action.accent} text-white shadow-lg shadow-[var(--glow)]`}
                                        >
                                            <Icon className="size-5" />
                                        </div>
                                        <h3 className="font-display text-lg font-semibold">{action.title}</h3>
                                        <p className="text-sm text-muted-foreground">{action.description}</p>
                                        <span className="inline-flex items-center gap-1 text-sm font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                                            Ouvrir <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
                                        </span>
                                    </CardContent>
                                </Card>
                            </Link>
                        );
                    })}
                </div>
                <div className="space-y-4">
                    {subscription && <UsageCard subscription={subscription} />}
                    <Card>
                        <CardContent className="flex items-center gap-4 pt-6">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src="/brand/empty-state.svg" alt="" aria-hidden className="h-16 w-auto" />
                            <div className="text-sm">
                                <p className="font-medium">IA souveraine</p>
                                <p className="text-muted-foreground">
                                    Modèles, voix et enregistrements restent sur votre infrastructure.
                                </p>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            </div>
        </PageShell>
    );
}

// Shared two-column auth shell, used by BOTH the Stack Auth handler
// (/handler/[...stack], cloud) and the local/OSS auth pages (/auth/login,
// /auth/signup). LEFT: a glass card that wraps the auth form (`children`) over
// the NIMBORA aurora. RIGHT (lg+ only): the brand panel — animated orbit
// illustration (agents around a voice core), headline and proof points, with
// the optional enterprise block (`enterpriseSlot`) at the bottom.
// Mobile collapses to the single card column.

import type { ReactNode } from "react";

import { BrandLogo } from "@/components/BrandLogo";

const HIGHLIGHTS = [
  "Agents vocaux IA",
  "Centre d'appels humain",
  "IA 100 % souveraine",
  "Multi-langues",
];

export function AuthShell({
  children,
  enterpriseSlot,
}: {
  children: ReactNode;
  enterpriseSlot?: ReactNode;
}) {
  return (
    <div className="grid min-h-screen w-full bg-background lg:grid-cols-[52%_48%]">
      {/* Form column (LEFT) — scrolls and stays centered so tall forms never clip. */}
      <main className="auth-imprint flex min-h-screen flex-col overflow-y-auto">
        <div className="page-enter flex min-h-full items-center justify-center p-6 sm:p-10">
          <div className="card-weave w-full max-w-md space-y-6 rounded-2xl border border-border/60 p-6 shadow-2xl shadow-black/20 sm:p-8">
            {/* Mobile-only logo (brand panel is hidden) */}
            <div className="lg:hidden">
              <BrandLogo className="h-9" />
            </div>
            {children}
          </div>
        </div>
      </main>

      {/* Brand panel (RIGHT) — hidden on mobile */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-l border-white/10 bg-[#060814] p-10 text-white lg:flex xl:p-14">
        {/* Aurora + star grid */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(55% 45% at 85% 15%, rgb(124 92 255 / 0.45), transparent 70%), radial-gradient(45% 40% at 0% 100%, rgb(34 229 255 / 0.22), transparent 70%)",
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-40 [background-image:radial-gradient(rgb(255_255_255_/_0.12)_1px,transparent_1px)] [background-size:26px_26px] [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]"
        />

        <div className="relative">
          <BrandLogo inverse className="h-10" />
        </div>

        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/auth-hero.svg"
          alt=""
          aria-hidden
          className="float-slow pointer-events-none absolute right-[-12%] top-1/2 w-[78%] max-w-[620px] -translate-y-1/2 opacity-90"
        />

        <div className="relative max-w-md space-y-5">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300/80">
            Centre d&apos;appels nouvelle génération
          </p>
          <h1 className="font-display text-4xl font-bold leading-[1.1] tracking-tight xl:text-5xl">
            Le centre d&apos;appels qui <span className="text-gradient">pense, parle et décide.</span>
          </h1>
          <p className="text-base text-slate-300/90">
            Des agents IA qui décrochent 24 h/24, passent la main à vos équipes au bon moment
            et gardent vos données chez vous.
          </p>
          <ul className="flex flex-wrap gap-2">
            {HIGHLIGHTS.map((point) => (
              <li
                key={point}
                className="rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-xs font-medium text-slate-200 backdrop-blur"
              >
                {point}
              </li>
            ))}
          </ul>
        </div>

        {enterpriseSlot ? (
          <div className="relative mb-6 max-w-md space-y-3 rounded-xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur">
            {enterpriseSlot}
          </div>
        ) : (
          <div className="relative mb-6 flex items-center gap-3 text-xs text-slate-400">
            <span className="signal-pulse inline-block size-2 rounded-full bg-[#34f5c5]" />
            Plateforme opérationnelle · hébergée sur votre infrastructure
          </div>
        )}
      </aside>
    </div>
  );
}

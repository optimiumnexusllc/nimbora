"use client";

import { useBrand } from "@/context/BrandContext";
import { DEFAULT_NAME } from "@/lib/brand";

/** The NIMBORA orbit illustration of the sign-in panel: not shown under another charter. */
export function BrandHeroArt() {
  const brand = useBrand();
  if (brand.name !== DEFAULT_NAME || brand.gradient || brand.logoUrl) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/brand/auth-hero.svg"
      alt=""
      aria-hidden
      className="float-slow pointer-events-none absolute right-[-12%] top-1/2 w-[78%] max-w-[620px] -translate-y-1/2 opacity-90"
    />
  );
}

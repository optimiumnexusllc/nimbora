import "./globals.css";
import "@fontsource-variable/space-grotesk";

import { GoogleTagManager } from "@next/third-parties/google";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import ChatwootWidget from "@/components/ChatwootWidget";
import { EventBanner } from "@/components/EventBanner";
import AppLayout from "@/components/layout/AppLayout";
import MetaPixel from "@/components/MetaPixel";
import PostHogIdentify from "@/components/PostHogIdentify";
import ReoProvider from "@/components/ReoProvider";
import { SentryErrorBoundary } from "@/components/SentryErrorBoundary";
import SpinLoader from "@/components/SpinLoader";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";
import { AppConfigProvider } from "@/context/AppConfigContext";
import { BrandProvider } from "@/context/BrandContext";
import { OnboardingProvider } from "@/context/OnboardingContext";
import { OrgConfigProvider } from "@/context/OrgConfigContext";
import { TelephonyConfigWarningsProvider } from "@/context/TelephonyConfigWarningsContext";
import { AuthProvider } from "@/lib/auth";
import { brandCss, DEFAULT_NAME, readBrand } from "@/lib/brand";


// Fonts are self-hosted (geist + @fontsource packages): no request to Google
// Fonts at build or run time, as befits a sovereign, on-premise platform.
const geistSans = GeistSans;
const geistMono = GeistMono;

// The charter (white label) is read from BRAND_* at request time, not at build
// time: `connection()` keeps the layout dynamic, so .env changes need no rebuild.
export async function generateMetadata(): Promise<Metadata> {
  await connection();
  const { name, faviconUrl } = readBrand(process.env);
  return {
    title: {
      default: `${name} — Centre d'appels IA`,
      template: `%s · ${name}`,
    },
    description:
      `${name} : agents vocaux IA, centre d'appels humain et IA souveraine, sur votre propre infrastructure.`,
    applicationName: name,
    openGraph: {
      title: `${name} — Le centre d'appels qui pense, parle et décide`,
      description: "Agents vocaux IA · centre d'appels humain · IA souveraine",
      siteName: name,
      type: "website",
      // The NIMBORA preview image only for NIMBORA (not a file-based
      // app/opengraph-image, which would show under every charter).
      ...(name === DEFAULT_NAME ? { images: "/brand/og-image.png" } : {}),
    },
    // Declared here, not as app/icon.svg / favicon.ico / apple-icon.png: file-based icons
    // would win over the charter's BRAND_FAVICON_URL.
    icons: faviconUrl
      ? { icon: faviconUrl, apple: faviconUrl }
      : {
          icon: [{ url: "/favicon.ico", sizes: "any" }, { url: "/icon.svg", type: "image/svg+xml" }],
          apple: "/apple-icon.png",
        },
  };
}

export const viewport = {
  themeColor: "#060814",
};

export default async function RootLayout({
  children
}: {
  children: React.ReactNode
}) {
  await connection();
  const brand = readBrand(process.env);
  // Validated values only (lib/brand.ts): safe inside <style>.
  const charterCss = brandCss(brand);
  const gtmId = process.env.NEXT_PUBLIC_GTM_ID?.trim();
  const metaPixelId = process.env.NEXT_PUBLIC_META_PIXEL_ID?.trim();
  const reoClientId = process.env.NEXT_PUBLIC_REO_CLIENT_ID?.trim();
  // NIMBORA Cloud only. Self-hosted/OSS installs leave this blank and never
  // render the event bar — same gating shape as the Meta Pixel above.
  const showEventBanner = process.env.NEXT_PUBLIC_EVENT_BANNER?.trim() === "1";

  return (
    <html lang="fr" className="dark" suppressHydrationWarning>
      <head>
        {/* Inline script to prevent flash of light theme - runs before React hydrates.
            Dark is the locked default: only an explicit stored 'light' opts out. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme');
                  if (theme === 'light') {
                    document.documentElement.classList.remove('dark');
                  } else {
                    document.documentElement.classList.add('dark');
                  }
                } catch (e) {
                  document.documentElement.classList.add('dark');
                }
              })();
            `,
          }}
        />
        {charterCss ? <style id="brand-charter" dangerouslySetInnerHTML={{ __html: charterCss }} /> : null}
      </head>
      <body
        suppressHydrationWarning
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        {gtmId ? <GoogleTagManager gtmId={gtmId} /> : null}
        {metaPixelId ? <MetaPixel pixelId={metaPixelId} /> : null}
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          <SentryErrorBoundary>
            {/* Above the app chrome on every route (auth pages included). It
                is sticky at top-0 and publishes --event-banner-h, which the
                header/sidebar offsets in AppLayout + globals.css consume. */}
            {showEventBanner ? <EventBanner /> : null}
            <BrandProvider brand={brand}>
            <AuthProvider>
              <AppConfigProvider>
                <Suspense fallback={<SpinLoader />}>
                  <OrgConfigProvider>
                    <TelephonyConfigWarningsProvider>
                      <OnboardingProvider>
                        <PostHogIdentify />
                        {reoClientId ? <ReoProvider clientId={reoClientId} /> : null}
                        <AppLayout>
                          {children}
                        </AppLayout>
                        <Toaster />
                        <ChatwootWidget />
                      </OnboardingProvider>
                    </TelephonyConfigWarningsProvider>
                  </OrgConfigProvider>
                </Suspense>
              </AppConfigProvider>
            </AuthProvider>
            </BrandProvider>
          </SentryErrorBoundary>
        </ThemeProvider>
      </body>
    </html>
  );
}

/**
 * The platform's charter (white label), read at run time from the same BRAND_*
 * variables as the API (api/services/branding.py), so an operator rebrands the
 * interface in .env without rebuilding the image.
 *
 * Files (logo, favicon, font) are URLs: an https:// address or a path on this
 * site, typically /brand-assets/<file> served from the mounted brand folder
 * (app/brand-assets/[file]/route.ts). Colours and the font are injected into a
 * <style> element, so every value is checked against a strict pattern and
 * dropped when it does not match.
 */

export interface Brand {
  name: string;
  pbxName: string;
  softphoneName: string;
  /** null: the NIMBORA artwork (default brand) or the name as text (custom). */
  logoUrl: string | null;
  logoDarkUrl: string | null;
  markUrl: string | null;
  faviconUrl: string | null;
  primaryColor: string | null;
  /** Three colours of the brand gradient (from, via, to). */
  gradient: [string, string, string] | null;
  fontFamily: string | null;
  fontUrl: string | null;
}

export const DEFAULT_NAME = "NIMBORA";

export const DEFAULT_BRAND: Brand = {
  name: DEFAULT_NAME,
  pbxName: `${DEFAULT_NAME} Voice`,
  softphoneName: `${DEFAULT_NAME} Softphone`,
  logoUrl: null,
  logoDarkUrl: null,
  markUrl: null,
  faviconUrl: null,
  primaryColor: null,
  gradient: null,
  fontFamily: null,
  fontUrl: null,
};

type Env = Record<string, string | undefined>;

const COLOR = /^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla|oklch|oklab)\([0-9a-zA-Z.,%/ +-]{1,60}\))$/;
const FONT_FAMILY = /^[A-Za-z0-9 _-]{1,60}$/;
// https:// anywhere, or a path on this site (not "//host", which leaves it).
const URL = /^(https:\/\/[^\s"'()<>\\]{1,500}|\/(?!\/)[^\s"'()<>\\]{0,500})$/;

function value(env: Env, key: string): string | null {
  const raw = env[key]?.trim();
  return raw ? raw : null;
}

function matching(env: Env, key: string, pattern: RegExp): string | null {
  const raw = value(env, key);
  return raw && pattern.test(raw) ? raw : null;
}

function text(env: Env, key: string): string | null {
  const raw = value(env, key)?.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 80).trim();
  return raw ? raw : null;
}

export function readBrand(env: Env): Brand {
  const name = text(env, "BRAND_NAME") ?? DEFAULT_NAME;
  const logoUrl = matching(env, "BRAND_LOGO_URL", URL);
  const gradient = (value(env, "BRAND_GRADIENT") ?? "").split(",").map(part => part.trim());
  return {
    name,
    pbxName: text(env, "BRAND_PBX_NAME") ?? `${name} Voice`,
    softphoneName: `${name} Softphone`,
    logoUrl,
    logoDarkUrl: matching(env, "BRAND_LOGO_DARK_URL", URL) ?? logoUrl,
    markUrl: matching(env, "BRAND_MARK_URL", URL),
    faviconUrl: matching(env, "BRAND_FAVICON_URL", URL),
    primaryColor: matching(env, "BRAND_PRIMARY_COLOR", COLOR),
    gradient:
      gradient.length === 3 && gradient.every(part => COLOR.test(part))
        ? (gradient as [string, string, string])
        : null,
    fontFamily: matching(env, "BRAND_FONT_FAMILY", FONT_FAMILY),
    fontUrl: matching(env, "BRAND_FONT_URL", URL),
  };
}

/** CSS overriding the theme's variables (empty for the default brand). */
export function brandCss(brand: Brand): string {
  const vars: string[] = [];
  if (brand.primaryColor) {
    for (const name of ["--primary", "--sidebar-primary", "--ring"]) {
      vars.push(`${name}: ${brand.primaryColor};`);
    }
  }
  if (brand.gradient) {
    const [from, via, to] = brand.gradient;
    vars.push(`--brand-cyan: ${from};`, `--brand-violet: ${via};`, `--brand-magenta: ${to};`);
  }
  if (brand.fontFamily) {
    vars.push(`--font-display: "${brand.fontFamily}", var(--font-geist-sans), sans-serif;`);
  }
  const rules: string[] = [];
  if (brand.fontFamily && brand.fontUrl) {
    rules.push(
      `@font-face { font-family: "${brand.fontFamily}"; src: url("${brand.fontUrl}"); font-display: swap; }`,
    );
  }
  if (vars.length) {
    // Both themes; html:root / html.dark outrank globals.css whatever the order.
    rules.push(`html:root, html.dark { ${vars.join(" ")} }`);
  }
  return rules.join("\n");
}

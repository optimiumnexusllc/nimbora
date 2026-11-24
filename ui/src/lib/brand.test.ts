import { describe, expect, it } from "vitest";

import { brandCss, DEFAULT_BRAND, readBrand } from "./brand";

describe("readBrand", () => {
  it("keeps NIMBORA when nothing is configured (unset or empty, as Compose passes it)", () => {
    expect(readBrand({})).toEqual(DEFAULT_BRAND);
    expect(readBrand({ BRAND_NAME: "", BRAND_PRIMARY_COLOR: "  " })).toEqual(DEFAULT_BRAND);
    expect(brandCss(DEFAULT_BRAND)).toBe("");
  });

  it("reads the operator's charter from the same BRAND_* variables as the API", () => {
    const brand = readBrand({
      BRAND_NAME: "Acme Voix",
      BRAND_PBX_NAME: "Acme Téléphonie",
      BRAND_LOGO_URL: "/brand-assets/logo.svg",
      BRAND_LOGO_DARK_URL: "/brand-assets/logo-dark.svg",
      BRAND_MARK_URL: "/brand-assets/mark.svg",
      BRAND_FAVICON_URL: "/brand-assets/favicon.png",
      BRAND_PRIMARY_COLOR: "#0a7d4f",
      BRAND_GRADIENT: "#0a7d4f, #11a36b, rgb(20 200 140)",
      BRAND_FONT_FAMILY: "Acme Sans",
      BRAND_FONT_URL: "/brand-assets/acme.woff2",
    });
    expect(brand).toMatchObject({
      name: "Acme Voix",
      pbxName: "Acme Téléphonie",
      softphoneName: "Acme Voix Softphone",
      logoUrl: "/brand-assets/logo.svg",
      logoDarkUrl: "/brand-assets/logo-dark.svg",
      markUrl: "/brand-assets/mark.svg",
      faviconUrl: "/brand-assets/favicon.png",
      primaryColor: "#0a7d4f",
      gradient: ["#0a7d4f", "#11a36b", "rgb(20 200 140)"],
      fontFamily: "Acme Sans",
      fontUrl: "/brand-assets/acme.woff2",
    });
    const css = brandCss(brand);
    expect(css).toContain("--primary: #0a7d4f;");
    expect(css).toContain("--sidebar-primary: #0a7d4f;");
    expect(css).toContain("--brand-cyan: #0a7d4f;");
    expect(css).toContain("--brand-magenta: rgb(20 200 140);");
    expect(css).toContain('font-family: "Acme Sans"');
    expect(css).toContain('src: url("/brand-assets/acme.woff2")');
    expect(css).toContain('--font-display: "Acme Sans"');
  });

  it("defaults the PBX name and logo variants from what is given", () => {
    const brand = readBrand({ BRAND_NAME: "Acme", BRAND_LOGO_URL: "https://cdn.acme.test/l.svg" });
    expect(brand.pbxName).toBe("Acme Voice");
    expect(brand.logoDarkUrl).toBe("https://cdn.acme.test/l.svg");
    // A custom name without a custom logo: the NIMBORA artwork is not shown.
    expect(readBrand({ BRAND_NAME: "Acme" }).logoUrl).toBeNull();
  });

  it("refuses values that could escape the injected <style> or the page", () => {
    const brand = readBrand({
      BRAND_PRIMARY_COLOR: "red;} body{display:none",
      BRAND_GRADIENT: "#fff, url(x), #000",
      BRAND_FONT_FAMILY: 'x"; } * { color: red',
      BRAND_FONT_URL: "javascript:alert(1)",
      BRAND_LOGO_URL: "javascript:alert(1)",
      BRAND_FAVICON_URL: "//evil.test/x.ico",
      BRAND_NAME: "Acme</title><script>",
    });
    expect(brand.primaryColor).toBeNull();
    expect(brand.gradient).toBeNull();
    expect(brand.fontFamily).toBeNull();
    expect(brand.fontUrl).toBeNull();
    expect(brand.logoUrl).toBeNull();
    expect(brand.faviconUrl).toBeNull();
    // The name is text (React escapes it); only control characters are dropped.
    expect(brand.name).toBe("Acme</title><script>");
    expect(brandCss(brand)).toBe("");
  });

  it("reads a gradient written without spaces, as .env needs it", () => {
    // In .env, " #" starts a comment: "#a, #b" would reach us as "#a,".
    expect(readBrand({ BRAND_GRADIENT: "#0a7d4f,#11a36b,#7bd389" }).gradient).toEqual([
      "#0a7d4f",
      "#11a36b",
      "#7bd389",
    ]);
    expect(readBrand({ BRAND_GRADIENT: "#0a7d4f," }).gradient).toBeNull();
  });
});

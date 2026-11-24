// @vitest-environment node
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GET } from "./route";

let dir: string;

function get(file: string) {
    return GET(new Request(`http://x/brand-assets/${file}`), { params: Promise.resolve({ file }) });
}

beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "brand-"));
    process.env.BRAND_ASSETS_DIR = dir;
    writeFileSync(join(dir, "logo.svg"), "<svg/>");
    writeFileSync(join(dir, "favicon.png"), "png");
    writeFileSync(join(dir, "secrets.env"), "KEY=1");
});
afterEach(() => {
    delete process.env.BRAND_ASSETS_DIR;
});

describe("GET /brand-assets/[file]", () => {
    it("serves the operator's files with their type, cached, never sniffed", async () => {
        const response = await get("logo.svg");
        expect(response.status).toBe(200);
        expect(await response.text()).toBe("<svg/>");
        expect(response.headers.get("content-type")).toBe("image/svg+xml");
        expect(response.headers.get("x-content-type-options")).toBe("nosniff");
        // An SVG opened on its own cannot run scripts on this origin.
        expect(response.headers.get("content-security-policy")).toContain("default-src 'none'");
        expect(response.headers.get("cache-control")).toContain("max-age=");
        expect((await get("favicon.png")).headers.get("content-type")).toBe("image/png");
    });

    it("serves only images and fonts, only from the brand folder", async () => {
        for (const file of ["secrets.env", "../etc/passwd", "..%2Fsecrets.env", ".hidden.svg", "missing.svg", "a/b.svg"]) {
            expect((await get(file)).status, file).toBe(404);
        }
    });

    it("answers 404 when no brand folder is mounted", async () => {
        process.env.BRAND_ASSETS_DIR = join(dir, "absent");
        expect((await get("logo.svg")).status).toBe(404);
    });
});

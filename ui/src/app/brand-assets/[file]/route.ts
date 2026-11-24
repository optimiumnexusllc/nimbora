import { readFile } from "node:fs/promises";
import { join } from "node:path";

/**
 * The operator's brand files (logo, favicon, font), served from the folder
 * mounted at BRAND_ASSETS_DIR (default /brand): the .env refers to them as
 * /brand-assets/<file> (lib/brand.ts). Read at request time, so a new logo
 * needs no rebuild. Only images and fonts, only directly in that folder.
 */
const TYPES: Record<string, string> = {
    svg: "image/svg+xml",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    webp: "image/webp",
    ico: "image/x-icon",
    woff2: "font/woff2",
    woff: "font/woff",
};
const NAME = /^[A-Za-z0-9_-][A-Za-z0-9._-]{0,100}\.([a-z0-9]+)$/;

export async function GET(_request: Request, { params }: { params: Promise<{ file: string }> }) {
    const { file } = await params;
    const match = NAME.exec(file);
    const type = match && !file.includes("..") ? TYPES[match[1]] : undefined;
    if (!type) return new Response("Not found", { status: 404 });
    let body: Buffer;
    try {
        body = await readFile(join(process.env.BRAND_ASSETS_DIR || "/brand", file));
    } catch {
        return new Response("Not found", { status: 404 });
    }
    return new Response(new Uint8Array(body), {
        headers: {
            "content-type": type,
            "cache-control": "public, max-age=300",
            "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    });
}

/** Pure helpers: numbers, durations, pairing links, platform detection. */

export type Platform = "windows" | "macos" | "linux" | "android" | "ios" | "web";

/** What the user typed → what we dial ("+225 07 07-11.22.33" → "+2250707112233"). */
export function cleanNumber(input: string): string {
    const trimmed = input.trim();
    const plus = trimmed.startsWith("+");
    const kept = trimmed.replace(/[^0-9*#]/g, "");
    return plus ? `+${kept}` : kept;
}

export function isDialable(input: string): boolean {
    return /^\+?[0-9*#]{2,32}$/.test(cleanNumber(input));
}

export function formatDuration(seconds: number): string {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** A SIP URI or display string → the number part. */
export function numberFromUri(uri: string | undefined | null): string {
    if (!uri) return "";
    const match = /sip:([^@;>]+)/i.exec(uri);
    return (match ? match[1] : uri).trim();
}

export type PairingLink = { server: string | null; code: string };

/**
 * "nimbora-softphone://activate?server=https%3A%2F%2Fapi.example&code=ABCD2345"
 * (or the same as a web link) → { server, code }. Null if it is not one.
 */
export function parsePairingLink(link: string | null | undefined): PairingLink | null {
    if (!link) return null;
    let raw = link.trim();
    if (raw.startsWith("web+nimbora:")) raw = raw.replace(/^web\+nimbora:\/*/, "nimbora-softphone://");
    let url: URL;
    try {
        url = new URL(raw);
    } catch {
        return null;
    }
    const isApp = url.protocol === "nimbora-softphone:";
    if (!isApp && !url.searchParams.has("code")) return null;
    const code = normalizeCode(url.searchParams.get("code") ?? "");
    if (code.length !== 8) return null;
    const server = url.searchParams.get("server");
    return { server: server ? normalizeServer(server) : null, code };
}

export function normalizeCode(code: string): string {
    return code.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function formatCode(code: string): string {
    const c = normalizeCode(code).slice(0, 8);
    return c.length > 4 ? `${c.slice(0, 4)}-${c.slice(4)}` : c;
}

/** "nimbora.example.com/" → "https://nimbora.example.com" (http only for localhost). */
export function normalizeServer(server: string): string {
    let s = server.trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(s)) s = `https://${s}`;
    const url = new URL(s);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.protocol === "http:" && !local) url.protocol = "https:";
    return url.toString().replace(/\/+$/, "");
}

export function detectPlatform(userAgent: string = typeof navigator !== "undefined" ? navigator.userAgent : ""): Platform {
    const ua = userAgent.toLowerCase();
    if (/android/.test(ua)) return "android";
    if (/iphone|ipad|ipod/.test(ua)) return "ios";
    if (/windows/.test(ua)) return "windows";
    if (/mac os x|macintosh/.test(ua)) return "macos";
    if (/linux|x11/.test(ua)) return "linux";
    return "web";
}

export const PLATFORM_LABELS: Record<Platform, string> = {
    windows: "Windows",
    macos: "macOS",
    linux: "Linux",
    android: "Android",
    ios: "iPhone / iPad",
    web: "Navigateur",
};

export function initials(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

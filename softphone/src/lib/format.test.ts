import { describe, expect, it } from "vitest";

import { cleanNumber, detectPlatform, formatCode, formatDuration, initials, isDialable, numberFromUri, parsePairingLink } from "./format";

describe("numbers", () => {
    it("cleans what people type", () => {
        expect(cleanNumber(" +225 07 07-11.22.33 ")).toBe("+2250707112233");
        expect(cleanNumber("*98")).toBe("*98");
        expect(isDialable("1001")).toBe(true);
        expect(isDialable("1")).toBe(false);
        expect(isDialable("appelle-moi")).toBe(false);
    });

    it("reads SIP identities and durations", () => {
        expect(numberFromUri("sip:+2250707112233@pbx.example;user=phone")).toBe("+2250707112233");
        expect(numberFromUri(null)).toBe("");
        expect(formatDuration(65)).toBe("1:05");
        expect(formatDuration(3725)).toBe("1:02:05");
        expect(initials("Koffi Yao Kouassi")).toBe("KK");
    });
});

describe("pairing links", () => {
    it("accepts app and web links", () => {
        expect(parsePairingLink("nimbora-softphone://activate?server=https%3A%2F%2Fapi.ivoire-immo.ci&code=abcd-2345")).toEqual({
            server: "https://api.ivoire-immo.ci",
            code: "ABCD2345",
        });
        expect(parsePairingLink("web+nimbora://activate?code=ABCD2345")).toEqual({ server: null, code: "ABCD2345" });
        expect(parsePairingLink("https://app.example/softphone/?code=ABCD2345&server=api.example")).toEqual({
            server: "https://api.example",
            code: "ABCD2345",
        });
    });

    it("refuses anything else", () => {
        expect(parsePairingLink("nimbora-softphone://activate?code=123")).toBeNull();
        expect(parsePairingLink("https://example.com/")).toBeNull();
        expect(parsePairingLink("pas un lien")).toBeNull();
        // Never downgrades a remote server to plain HTTP.
        expect(parsePairingLink("nimbora-softphone://activate?server=http%3A%2F%2Fevil.example&code=ABCD2345")?.server).toBe("https://evil.example");
        expect(formatCode("abcd2345")).toBe("ABCD-2345");
    });

    it("detects the platform", () => {
        expect(detectPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("windows");
        expect(detectPlatform("Mozilla/5.0 (Linux; Android 14; Pixel 8)")).toBe("android");
        expect(detectPlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")).toBe("ios");
        expect(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)")).toBe("macos");
        expect(detectPlatform("Mozilla/5.0 (X11; Linux x86_64)")).toBe("linux");
    });
});

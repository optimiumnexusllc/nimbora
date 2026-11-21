import { describe, expect, it } from "vitest";

import { formatDuration } from "./format";
import { buildFeed, type LiveEvent } from "./LiveCallPanel";

const e = (seq: number, kind: string, extra: Partial<LiveEvent> = {}): LiveEvent => ({ seq, kind, at: seq, ...extra });

describe("supervision feed", () => {
    it("merges chunked agent speech and labels supervisor actions", () => {
        const feed = buildFeed([
            e(1, "started"),
            e(2, "caller", { text: "Je veux résilier" }),
            e(3, "agent", { text: "Je comprends," }),
            e(4, "agent", { text: "voyons cela." }),
            e(5, "tool", { name: "lookup_contract" }),
            e(6, "supervisor", { action: "instruct", text: "Propose 10 %", status: "ok" }),
            e(7, "supervisor", { action: "takeover", status: "error", error: "no agent" }),
            e(8, "ended"),
        ]);
        expect(feed.map((i) => i.text)).toEqual([
            "Je veux résilier",
            "Je comprends, voyons cela.",
            "Outil : lookup_contract",
            "Consigne soufflée à l'IA — « Propose 10 % »",
            "Transfert vers un conseiller (échec : no agent)",
            "Appel terminé",
        ]);
    });

    it("formats durations", () => {
        expect(formatDuration(5)).toBe("0:05");
        expect(formatDuration(75)).toBe("1:15");
        expect(formatDuration(3725)).toBe("1:02:05");
    });
});

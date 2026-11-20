import { describe, expect, it } from "vitest";

import { formatWhen } from "./CallbacksPanel";

describe("formatWhen", () => {
    const now = new Date(2026, 10, 20, 9, 0);

    it("flags overdue callbacks", () => {
        expect(formatWhen(new Date(2026, 10, 20, 8, 40).toISOString(), now)).toBe("en retard de 20 min");
        expect(formatWhen(new Date(2026, 10, 20, 6, 0).toISOString(), now)).toBe("en retard de 3 h");
        expect(formatWhen(now.toISOString(), now)).toBe("maintenant");
    });

    it("says when upcoming callbacks are due", () => {
        expect(formatWhen(new Date(2026, 10, 20, 9, 25).toISOString(), now)).toBe("dans 25 min");
        expect(formatWhen(new Date(2026, 10, 20, 15, 30).toISOString(), now)).toBe("aujourd'hui à 15:30");
        expect(formatWhen(new Date(2026, 10, 21, 10, 0).toISOString(), now)).toBe("demain à 10:00");
    });
});

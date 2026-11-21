import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectOption } from "@/components/model-connections/test-helpers";

import { AiOutboundCard, previewNumber } from "./AiOutboundCard";
import type { PbxTrunk } from "./types";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("@/client/sdk.gen", () => ({
    readAiOutboundApiV1PbxAiOutboundGet: mocks.read,
    saveAiOutboundApiV1PbxAiOutboundPut: mocks.save,
}));

const trunks: PbxTrunk[] = [
    { id: 40, label: "Orange", technology: "sip", host: "sip.orange.ci", username: null, registration: false, registered: null, current_calls: 0, outcalls: [], caller_id_format: "+E164" },
];
const settings = {
    mode: "custom", trunk_id: null, dial_string_template: "PJSIP/{number}", number_format: "as_is",
    country_code: "", national_prefix: "", caller_id: null, example: { number: "+2250707112233", dial_string: "PJSIP/+2250707112233" },
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: settings });
    mocks.save.mockResolvedValue({ data: { ...settings, mode: "trunk", trunk_id: 40 } });
});

describe("AiOutboundCard", () => {
    it("previews the rewritten number like the backend", () => {
        const base = { country_code: "225", national_prefix: "" };
        expect(previewNumber("+2250707112233", { ...base, number_format: "national" })).toBe("0707112233");
        expect(previewNumber("+33612345678", { ...base, number_format: "national" })).toBe("0033612345678");
        expect(previewNumber("+33612345678", { country_code: "33", national_prefix: "0", number_format: "national" })).toBe("0612345678");
        expect(previewNumber("+33612345678", { ...base, number_format: "international_00" })).toBe("0033612345678");
        expect(previewNumber("+33612345678", { ...base, number_format: "as_is" })).toBe("+33612345678");
    });

    it("sends AI calls out through one line with the company number", async () => {
        render(<AiOutboundCard trunks={trunks} hasRoutes={false} />);
        expect(await screen.findByText(/Réglage actuel personnalisé/)).toBeTruthy();
        fireEvent.click(screen.getByRole("radio", { name: "Par une ligne précise" }));
        selectOption(screen.getByRole("combobox", { name: "Format du numéro composé" }), "National (07…)");
        fireEvent.change(screen.getByLabelText("Indicatif du pays"), { target: { value: "225" } });
        fireEvent.change(screen.getByLabelText("Numéro présenté"), { target: { value: "+225 27 22 00 00 00" } });
        expect(screen.getByTestId("ai-outbound-preview").textContent).toContain("compose 0707112233 sur Orange, présenté +225 27 22 00 00 00");
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));
        });
        expect(mocks.save).toHaveBeenCalledWith({
            body: { mode: "trunk", trunk_id: 40, number_format: "national", country_code: "225", national_prefix: "", caller_id: "+225 27 22 00 00 00" },
        });
        expect(mocks.toast.success).toHaveBeenCalled();
    });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/http", () => ({
    CredentialSelector: ({ label }: { label: string }) => <div>{label}</div>,
}));
vi.mock("@/client/sdk.gen", () => ({ previewSlotsApiV1ActionsCalendarsToolUuidPreviewPost: vi.fn() }));

import { CreateTicketToolConfig, parseRanges, SendMessageToolConfig } from "./ActionToolConfigs";

const common = { name: "T", onNameChange: vi.fn(), description: "", onDescriptionChange: vi.fn() };

describe("action tool editors", () => {
    it("parses opening hours typed loosely", () => {
        expect(parseRanges("9h-12h, 14:00-18:00")).toEqual(["09:00-12:00", "14:00-18:00"]);
        expect(parseRanges("8h30-12h; n importe quoi")).toEqual(["08:30-12:00"]);
        expect(parseRanges("")).toEqual([]);
    });

    it("shows the fields of the chosen messaging provider", () => {
        const onChange = vi.fn();
        const { rerender } = render(
            <SendMessageToolConfig {...common} config={{ channel: "sms", provider: "http" }} onChange={onChange} />,
        );
        expect(screen.getByText("Gateway URL")).toBeTruthy();
        expect(screen.getByText("Gateway credential")).toBeTruthy();
        rerender(<SendMessageToolConfig {...common} config={{ channel: "email", provider: "smtp" }} onChange={onChange} />);
        expect(screen.getByText("SMTP server")).toBeTruthy();
        expect(screen.getByText("SMTP login")).toBeTruthy();
        fireEvent.change(screen.getByPlaceholderText("smtp.acme.fr"), { target: { value: "smtp.ovh.net" } });
        expect(onChange).toHaveBeenLastCalledWith({ channel: "email", provider: "smtp", smtp_host: "smtp.ovh.net" });
    });

    it("asks for a domain and credential for external helpdesks only", () => {
        const { rerender } = render(<CreateTicketToolConfig {...common} config={{ provider: "nimbora" }} onChange={vi.fn()} />);
        expect(screen.queryByText("Domain")).toBeNull();
        rerender(<CreateTicketToolConfig {...common} config={{ provider: "zendesk" }} onChange={vi.fn()} />);
        expect(screen.getByText("Domain")).toBeTruthy();
        expect(screen.getByText("Zendesk API access")).toBeTruthy();
    });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HoldMusicCard } from "./HoldMusicCard";

const mocks = vi.hoisted(() => ({ read: vi.fn(), publish: vi.fn(), remove: vi.fn(), sample: vi.fn(), preview: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/client/sdk.gen", () => ({
    getHoldMusicApiV1PbxHoldMusicGet: mocks.read,
    publishHoldMusicApiV1PbxHoldMusicPost: mocks.publish,
    removeHoldMusicApiV1PbxHoldMusicDelete: mocks.remove,
    holdMusicSampleApiV1PbxHoldMusicSampleGet: mocks.sample,
    previewPromptApiV1PbxPromptsPreviewPost: mocks.preview,
}));

const workflows = [{ id: 4, name: "Accueil" }] as never;
const idle = {
    active: false,
    music: false,
    announcement: false,
    queues: 0,
    parking_lots: 0,
    suggested_announcement: "Merci de patienter, un conseiller va vous répondre dans un instant.",
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: idle });
});

describe("HoldMusicCard", () => {
    it("suggests the announcement in the company's language and publishes it with the generated music", async () => {
        mocks.publish.mockResolvedValue({ data: { ...idle, active: true, music: true, announcement: true, queues: 2, parking_lots: 1 } });
        render(<HoldMusicCard workflows={workflows} />);
        expect(await screen.findByText("Musique par défaut du PBX.")).toBeTruthy();
        const text = screen.getByLabelText("Annonce (facultative)") as HTMLTextAreaElement;
        expect(text.value).toBe(idle.suggested_announcement);

        fireEvent.click(screen.getByRole("button", { name: /Publier sur le PBX/ }));
        await waitFor(() => expect(mocks.publish).toHaveBeenCalled());
        expect(mocks.publish.mock.calls[0][0].body).toEqual({ music: "generated", announcement: idle.suggested_announcement });
        expect(await screen.findByText("En service")).toBeTruthy();
        expect(screen.getByText(/2 files et 1 parcage · avec annonce/)).toBeTruthy();
        expect(screen.getByRole("button", { name: /Revenir à la musique du PBX/ })).toBeTruthy();
    });

    it("sends the company's own music file", async () => {
        mocks.publish.mockResolvedValue({ data: { ...idle, active: true, music: true } });
        const { container } = render(<HoldMusicCard workflows={workflows} />);
        await screen.findByText("Musique par défaut du PBX.");
        const file = new File(["RIFF"], "jingle.wav", { type: "audio/wav" });
        fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
        expect(screen.getByText("jingle.wav")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Publier sur le PBX/ }));
        await waitFor(() => expect(mocks.publish).toHaveBeenCalled());
        expect(mocks.publish.mock.calls[0][0].body.music).toBe("custom");
        expect(mocks.publish.mock.calls[0][0].body.music_file).toBe(file);
    });

    it("cannot publish silence", async () => {
        render(<HoldMusicCard workflows={workflows} />);
        await screen.findByText("Musique par défaut du PBX.");
        fireEvent.click(screen.getByRole("radio", { name: /Pas de musique/ }));
        fireEvent.change(screen.getByLabelText("Annonce (facultative)"), { target: { value: "  " } });
        expect((screen.getByRole("button", { name: /Publier sur le PBX/ }) as HTMLButtonElement).disabled).toBe(true);
    });

    it("goes back to the PBX's default music", async () => {
        mocks.read.mockResolvedValue({ data: { ...idle, active: true, music: true, queues: 1 } });
        mocks.remove.mockResolvedValue({ data: undefined });
        render(<HoldMusicCard workflows={workflows} />);
        fireEvent.click(await screen.findByRole("button", { name: /Revenir à la musique du PBX/ }));
        await waitFor(() => expect(mocks.remove).toHaveBeenCalled());
        expect(await screen.findByText("Musique par défaut du PBX.")).toBeTruthy();
    });
});

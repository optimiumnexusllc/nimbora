"""Language packs for the self-hosted voice stack (Speaches + Ollama/vLLM).

A pack ties one language to what each local engine needs:

* STT: the Whisper language code (faster-whisper large-v3 / turbo handles
  ~100 languages, including Swahili, Hausa, Yoruba, Lingala, Shona, Somali,
  Amharic, Malagasy and Arabic; Wolof is not among them);
* TTS: a Speaches model id and voice. Kokoro (Apache-2.0) covers the major
  languages with natural voices; Piper voices (rhasspy/piper-voices, mostly
  MIT/CC-BY — check each voice's model card before commercial use) fill the
  gaps, e.g. Swahili or Arabic.

``scripts/local_ai/pull_models.sh`` downloads every model referenced here into
the Speaches cache. Operators add languages by adding entries — no code change
elsewhere. Model ids may need adjusting to what your Speaches version lists
(``GET /v1/models``); the setup script reports any that are missing.
"""

from __future__ import annotations

from dataclasses import dataclass

KOKORO_MODEL = "speaches-ai/Kokoro-82M-v1.0-ONNX"


def piper(voice: str) -> str:
    return f"speaches-ai/piper-{voice}"


@dataclass(frozen=True)
class VoiceOption:
    model: str
    voice: str
    label: str
    gender: str  # "female" | "male"


@dataclass(frozen=True)
class LanguagePack:
    code: str  # ISO 639-1, also the Whisper language code
    name: str  # name in the language itself
    voices: tuple[VoiceOption, ...]
    stt_language: str | None = None  # defaults to ``code``
    note: str = ""

    @property
    def whisper_language(self) -> str:
        return self.stt_language or self.code

    @property
    def default_voice(self) -> VoiceOption | None:
        return self.voices[0] if self.voices else None


LANGUAGE_PACKS: dict[str, LanguagePack] = {
    pack.code: pack
    for pack in (
        LanguagePack(
            "fr",
            "Français",
            (
                VoiceOption(KOKORO_MODEL, "ff_siwis", "Siwis (Kokoro)", "female"),
                VoiceOption(
                    piper("fr_FR-siwis-medium"), "siwis", "Siwis (Piper)", "female"
                ),
                VoiceOption(piper("fr_FR-tom-medium"), "tom", "Tom (Piper)", "male"),
                VoiceOption(piper("fr_FR-upmc-medium"), "upmc", "UPMC (Piper)", "male"),
            ),
        ),
        LanguagePack(
            "en",
            "English",
            (
                VoiceOption(KOKORO_MODEL, "af_heart", "Heart (US)", "female"),
                VoiceOption(KOKORO_MODEL, "am_michael", "Michael (US)", "male"),
                VoiceOption(KOKORO_MODEL, "bf_emma", "Emma (UK)", "female"),
                VoiceOption(KOKORO_MODEL, "bm_george", "George (UK)", "male"),
            ),
        ),
        LanguagePack(
            "es",
            "Español",
            (
                VoiceOption(KOKORO_MODEL, "ef_dora", "Dora", "female"),
                VoiceOption(KOKORO_MODEL, "em_alex", "Alex", "male"),
            ),
        ),
        LanguagePack(
            "pt",
            "Português",
            (
                VoiceOption(KOKORO_MODEL, "pf_dora", "Dora (BR)", "female"),
                VoiceOption(KOKORO_MODEL, "pm_alex", "Alex (BR)", "male"),
            ),
        ),
        LanguagePack(
            "it",
            "Italiano",
            (
                VoiceOption(KOKORO_MODEL, "if_sara", "Sara", "female"),
                VoiceOption(KOKORO_MODEL, "im_nicola", "Nicola", "male"),
            ),
        ),
        LanguagePack(
            "de",
            "Deutsch",
            (
                VoiceOption(
                    piper("de_DE-thorsten-medium"), "thorsten", "Thorsten", "male"
                ),
            ),
        ),
        LanguagePack(
            "ar",
            "العربية",
            (VoiceOption(piper("ar_JO-kareem-medium"), "kareem", "Kareem", "male"),),
        ),
        LanguagePack(
            "sw",
            "Kiswahili",
            (
                VoiceOption(
                    piper("sw_CD-lanfrica-medium"), "lanfrica", "Lanfrica", "male"
                ),
            ),
        ),
        LanguagePack(
            "hi",
            "हिन्दी",
            (
                VoiceOption(KOKORO_MODEL, "hf_alpha", "Alpha", "female"),
                VoiceOption(KOKORO_MODEL, "hm_omega", "Omega", "male"),
            ),
        ),
        LanguagePack(
            "zh",
            "中文",
            (VoiceOption(KOKORO_MODEL, "zf_xiaobei", "Xiaobei", "female"),),
        ),
        LanguagePack(
            "ja",
            "日本語",
            (VoiceOption(KOKORO_MODEL, "jf_alpha", "Alpha", "female"),),
        ),
        LanguagePack(
            "ru",
            "Русский",
            (VoiceOption(piper("ru_RU-irina-medium"), "irina", "Irina", "female"),),
        ),
        LanguagePack(
            "tr",
            "Türkçe",
            (VoiceOption(piper("tr_TR-dfki-medium"), "dfki", "DFKI", "male"),),
        ),
        # Understood by Whisper (STT) but without a good open TTS voice yet:
        # agents can listen in these languages and answer in French/English, or
        # operators can add a voice from the community (see docs/enterprise).
        LanguagePack("ha", "Hausa", (), note="STT only — add a TTS voice"),
        LanguagePack("yo", "Yorùbá", (), note="STT only — add a TTS voice"),
        LanguagePack("ln", "Lingála", (), note="STT only — add a TTS voice"),
        LanguagePack("am", "አማርኛ", (), note="STT only — add a TTS voice"),
        LanguagePack("so", "Soomaali", (), note="STT only — add a TTS voice"),
        LanguagePack("sn", "chiShona", (), note="STT only — add a TTS voice"),
        LanguagePack("mg", "Malagasy", (), note="STT only — add a TTS voice"),
    )
}

# Every language faster-whisper (large-v3) accepts, for the STT picker.
WHISPER_LANGUAGES = [
    "af",
    "am",
    "ar",
    "as",
    "az",
    "ba",
    "be",
    "bg",
    "bn",
    "bo",
    "br",
    "bs",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fo",
    "fr",
    "gl",
    "gu",
    "ha",
    "haw",
    "he",
    "hi",
    "hr",
    "ht",
    "hu",
    "hy",
    "id",
    "is",
    "it",
    "ja",
    "jw",
    "ka",
    "kk",
    "km",
    "kn",
    "ko",
    "la",
    "lb",
    "ln",
    "lo",
    "lt",
    "lv",
    "mg",
    "mi",
    "mk",
    "ml",
    "mn",
    "mr",
    "ms",
    "mt",
    "my",
    "ne",
    "nl",
    "nn",
    "no",
    "oc",
    "pa",
    "pl",
    "ps",
    "pt",
    "ro",
    "ru",
    "sa",
    "sd",
    "si",
    "sk",
    "sl",
    "sn",
    "so",
    "sq",
    "sr",
    "su",
    "sv",
    "sw",
    "ta",
    "te",
    "tg",
    "th",
    "tk",
    "tl",
    "tr",
    "tt",
    "uk",
    "ur",
    "uz",
    "vi",
    "yi",
    "yo",
    "yue",
    "zh",
]


def get_language_pack(code: str) -> LanguagePack:
    pack = LANGUAGE_PACKS.get((code or "").lower())
    if pack is None:
        raise KeyError(f"No language pack for {code!r}")
    return pack


def all_tts_models() -> list[str]:
    seen: dict[str, None] = {}
    for pack in LANGUAGE_PACKS.values():
        for voice in pack.voices:
            seen.setdefault(voice.model, None)
    return list(seen)

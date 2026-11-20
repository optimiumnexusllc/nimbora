"""Which language is the caller speaking?

Two signals, strongest first:

1. the STT engine's own detection (Whisper ``verbose_json`` language, Deepgram
   ``multi`` languages…), carried on ``TranscriptionFrame.language``;
2. a light text detector of our own, for engines that transcribe many
   languages without saying which: writing system first (Arabic, Ethiopic,
   Cyrillic, Devanagari, CJK…), then frequent function words for languages
   written in Latin script.

Neither is trusted on a single short utterance: :class:`LanguageSwitchPolicy`
decides when the conversation really changed language, so a caller saying
"OK" or a brand name never flips the agent's voice.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Whisper (OpenAI API) answers with English names; servers built on
# faster-whisper answer with codes. Both normalize to ISO 639-1.
_NAME_TO_CODE = {
    "afrikaans": "af",
    "amharic": "am",
    "arabic": "ar",
    "bengali": "bn",
    "chinese": "zh",
    "mandarin": "zh",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hausa": "ha",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "igbo": "ig",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "lingala": "ln",
    "malagasy": "mg",
    "malay": "ms",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "shona": "sn",
    "somali": "so",
    "spanish": "es",
    "castilian": "es",
    "swahili": "sw",
    "swedish": "sv",
    "tamil": "ta",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "vietnamese": "vi",
    "wolof": "wo",
    "yoruba": "yo",
    "zulu": "zu",
}

# English names, for the instruction given to the LLM.
LANGUAGE_NAMES = {code: name.capitalize() for name, code in _NAME_TO_CODE.items()}
LANGUAGE_NAMES.update({"zh": "Chinese (Mandarin)", "es": "Spanish", "ms": "Malay"})

_CODE_RE = re.compile(r"^[a-z]{2,3}$")


def normalize_language_code(value: object) -> str | None:
    """``Language.FR_FR`` / ``"fr-FR"`` / ``"French"`` / ``"fr"`` -> ``"fr"``."""
    if value is None:
        return None
    text = str(getattr(value, "value", value)).strip().lower()
    if not text or text in {"auto", "multi", "unknown", "none"}:
        return None
    if text in _NAME_TO_CODE:
        return _NAME_TO_CODE[text]
    base = re.split(r"[-_]", text, maxsplit=1)[0]
    return base if _CODE_RE.match(base) else None


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


# ------------------------------------------------------------- text detector

# Unicode script -> language, when a script identifies the language well
# enough for a phone call (Arabic script is Arabic here, not Urdu/Persian,
# unless those are among the allowed languages).
_SCRIPT_LANGUAGES = (
    ("ARABIC", ("ar", "fa", "ur")),
    ("ETHIOPIC", ("am",)),
    ("CYRILLIC", ("ru", "uk")),
    ("DEVANAGARI", ("hi",)),
    ("HIRAGANA", ("ja",)),
    ("KATAKANA", ("ja",)),
    ("HANGUL", ("ko",)),
    ("CJK", ("zh", "ja")),
    ("HEBREW", ("he",)),
    ("GREEK", ("el",)),
    ("THAI", ("th",)),
    ("BENGALI", ("bn",)),
    ("TAMIL", ("ta",)),
)

# Frequent, distinctive words. Kept short on purpose: a phone utterance has
# few words, and these are the ones callers actually say.
_STOPWORDS: dict[str, set[str]] = {
    "fr": set(
        "je j tu il elle nous vous ils est suis c ça ce cette les des une un le la "
        "du de et pour pas ne mais oui non merci bonjour bonsoir avec dans sur "
        "mon ma mes votre vos qui que quoi comment pourquoi voudrais veux peux "
        "aussi très bien d'accord parce s'il plaît rappeler appel".split()
    ),
    "en": set(
        "i you he she we they is am are the a an and to of for not but yes no "
        "thanks thank hello hi with in on my your what how why would want can "
        "please call could this that it's i'm don't have".split()
    ),
    "es": set(
        "yo tú usted él ella nosotros es soy está estoy el la los las un una y de "
        "para no pero sí gracias hola con en mi su qué cómo por quiero puedo "
        "favor llamar también muy bueno".split()
    ),
    "pt": set(
        "eu você ele ela nós é sou está estou o a os as um uma e de para não mas "
        "sim obrigado obrigada olá com em meu minha seu que como porque quero "
        "posso favor ligar também muito bom".split()
    ),
    "it": set(
        "io tu lui lei noi è sono sta il lo la gli le un una e di per non ma sì "
        "grazie ciao buongiorno con in mio mia suo che come perché voglio posso "
        "favore chiamare anche molto bene".split()
    ),
    "de": set(
        "ich du er sie wir ist bin sind der die das ein eine und zu von für nicht "
        "aber ja nein danke hallo guten tag mit in auf mein meine ihr was wie warum "
        "möchte will kann bitte anrufen auch sehr gut".split()
    ),
    "nl": set(
        "ik jij je hij zij wij is ben zijn de het een en te van voor niet maar ja "
        "nee dank bedankt hallo met in op mijn uw wat hoe waarom wil kan graag "
        "bellen ook heel goed".split()
    ),
    "sw": set(
        "mimi wewe yeye sisi ni na ya wa kwa la za katika hapana ndiyo ndio asante "
        "habari jambo nataka naweza tafadhali sana nzuri pia lakini hii huyu "
        "simu kupiga".split()
    ),
    "ha": set(
        "ina kai ke shi ita mu su da na ta a ba wannan yaya sannu nagode don allah "
        "ina so zan iya kira lafiya".split()
    ),
    "yo": set("mo o a won ni ti si fun kò bẹẹ ẹ jọwọ ṣe dupe ẹ kú báwo mi rẹ".split()),
    "ln": set(
        "ngai yo ye biso bino bango ezali na ya te boye mbote melesi nalingi "
        "nakoki bolamu".split()
    ),
    "tr": set(
        "ben sen o biz siz bir ve için değil ama evet hayır teşekkür merhaba ile "
        "benim sizin ne nasıl neden istiyorum lütfen aramak çok iyi".split()
    ),
    "so": set(
        "aniga adiga isaga waxaan waa iyo ka ku u ma haa maya mahadsanid "
        "salaan waxaan rabaa fadlan".split()
    ),
    "mg": set(
        "aho ianao izy isika dia ny sy amin ho tsy eny misaotra manao ahoana "
        "te hiantso azafady".split()
    ),
    "sn": set(
        "ini iwe iye isu ndi uye kwa ne kuti hongu kwete ndatenda mhoro ndinoda".split()
    ),
}

_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            continue
        for script, _ in _SCRIPT_LANGUAGES:
            if name.startswith(script) or (script == "CJK" and "CJK" in name):
                counts[script] = counts.get(script, 0) + 1
                break
        else:
            counts["LATIN"] = counts.get("LATIN", 0) + 1
    return counts


def detect_text_language(
    text: str, candidates: set[str] | None = None
) -> tuple[str | None, float]:
    """Best guess for ``text`` and a 0..1 confidence (0 = no idea)."""
    counts = _script_counts(text or "")
    total = sum(counts.values())
    if not total:
        return None, 0.0
    script, script_count = max(counts.items(), key=lambda item: item[1])
    if script != "LATIN" and script_count / total >= 0.5:
        for name, languages in _SCRIPT_LANGUAGES:
            if name == script:
                allowed = [c for c in languages if not candidates or c in candidates]
                if allowed:
                    return allowed[0], min(1.0, 0.6 + script_count / total * 0.4)
        return None, 0.0

    words = [w.lower().replace("’", "'") for w in _WORD_RE.findall(text)]
    if not words:
        return None, 0.0
    # Split French/Italian elisions: "j'ai" -> "j", "ai"; "l'appel" -> "l", "appel".
    tokens: list[str] = []
    for word in words:
        tokens.extend(part for part in word.split("'") if part)
        if "'" in word:
            tokens.append(word)
    scores = {
        code: sum(1 for t in tokens if t in vocab)
        for code, vocab in _STOPWORDS.items()
        if not candidates or code in candidates
    }
    if not scores:
        return None, 0.0
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if best_score == 0 or best_score == runner_up:
        return None, 0.0
    coverage = best_score / max(len(words), 1)
    margin = (best_score - runner_up) / best_score
    return best, round(min(1.0, coverage * 1.5) * margin, 3)


# -------------------------------------------------------------- switch policy


@dataclass
class LanguageSwitchPolicy:
    """Decide when the conversation changed language.

    * a language outside ``allowed`` (when set) is ignored;
    * utterances shorter than ``min_words`` never count ("ok", "allô");
    * a confident STT detection on a long utterance switches at once;
    * otherwise the same new language must be heard ``confirm_turns`` times
      in a row (a single foreign word or name does not switch).
    """

    current: str
    allowed: set[str] | None = None
    min_words: int = 2
    confirm_turns: int = 2
    immediate_words: int = 5
    _pending: str | None = field(default=None, init=False)
    _pending_count: int = field(default=0, init=False)

    def observe(
        self,
        text: str,
        reported_language: object = None,
        *,
        text_confidence_floor: float = 0.35,
    ) -> str | None:
        """Feed one final transcript. Returns the new language on a switch."""
        words = count_words(text)
        if words < self.min_words:
            return None
        reported = normalize_language_code(reported_language)
        if reported and self.allowed and reported not in self.allowed:
            reported = None
        candidate = reported
        strong = bool(reported) and words >= self.immediate_words
        if candidate is None:
            guess, confidence = detect_text_language(text, self.allowed)
            if guess is None or confidence < text_confidence_floor:
                return None
            candidate = guess
            strong = confidence >= 0.8 and words >= self.immediate_words + 2

        if candidate == self.current:
            self._pending, self._pending_count = None, 0
            return None
        if candidate == self._pending:
            self._pending_count += 1
        else:
            self._pending, self._pending_count = candidate, 1
        if strong or self._pending_count >= self.confirm_turns:
            self.current = candidate
            self._pending, self._pending_count = None, 0
            return candidate
        return None


# ---------------------------------------------------------- prompt directive

DIRECTIVE_HEADER = "## Conversation language"


def language_directive(code: str) -> str:
    name = language_name(code)
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"The caller is speaking {name} (language code: {code}). From now on, "
        f"reply only in {name}, including greetings, confirmations, numbers, "
        "dates and anything said around tool calls. Keep names, references and "
        "e-mail addresses exactly as given. If the caller switches language "
        "again, follow them."
    )


def with_language_directive(prompt: str, directive: str | None) -> str:
    """Replace (or remove) the language section at the end of a prompt."""
    base = prompt or ""
    marker = base.find(DIRECTIVE_HEADER)
    if marker != -1:
        base = base[:marker].rstrip()
    if not directive:
        return base
    return f"{base}\n\n{directive}" if base else directive

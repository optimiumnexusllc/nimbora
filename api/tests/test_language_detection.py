"""Automatic language detection: detector, switch policy, voices, controller."""

from types import SimpleNamespace

import pytest
from pipecat.services.settings import LLMSettings, TTSSettings
from pydantic import ValidationError

from api.services.language.controller import CallLanguageController, build_controller
from api.services.language.detection import (
    DIRECTIVE_HEADER,
    LanguageSwitchPolicy,
    detect_text_language,
    language_directive,
    normalize_language_code,
    with_language_directive,
)
from api.services.language.voices import resolve_voice


def test_language_codes_normalize():
    from pipecat.transcriptions.language import Language

    assert normalize_language_code("French") == "fr"
    assert normalize_language_code("fr-FR") == "fr"
    assert normalize_language_code(Language.EN_US) == "en"
    assert normalize_language_code("sw") == "sw"
    assert normalize_language_code("auto") is None
    assert normalize_language_code("multi") is None
    assert normalize_language_code(None) is None
    assert normalize_language_code("12") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bonjour, je voudrais savoir où en est ma commande", "fr"),
        ("Hello, I would like to know where my order is", "en"),
        ("Hola, quiero saber dónde está mi pedido", "es"),
        ("Olá, eu quero saber onde está o meu pedido", "pt"),
        ("Guten Tag, ich möchte bitte meine Bestellung ändern", "de"),
        ("Habari, nataka kujua simu yangu", "sw"),
        ("مرحبا أريد أن أعرف أين طلبي", "ar"),
        ("Здравствуйте, где мой заказ", "ru"),
        ("ሰላም ትዕዛዜ የት ነው", "am"),
    ],
)
def test_text_detector(text, expected):
    language, confidence = detect_text_language(text)
    assert language == expected
    assert confidence > 0.35


def test_text_detector_abstains_on_names_and_fillers():
    assert detect_text_language("ok")[0] is None
    assert detect_text_language("iPhone 15 Pro")[0] is None
    assert detect_text_language("12 34 56")[0] is None
    # Restricted to the allowed languages.
    assert detect_text_language("مرحبا", {"fr", "en"})[0] is None


def test_policy_needs_confirmation_unless_strong():
    policy = LanguageSwitchPolicy(current="fr")
    assert policy.observe("ok") is None  # too short
    # One English sentence from the text detector: pending, not switched.
    assert policy.observe("Hello I need help") is None
    assert policy.current == "fr"
    # Same language again: switch.
    assert policy.observe("Can you call me back please") == "en"
    assert policy.current == "en"
    # STT-reported language on a long utterance switches at once.
    assert (
        policy.observe("Quiero cambiar la dirección de entrega", reported_language="es")
        == "es"
    )


def test_policy_ignores_isolated_foreign_words_and_disallowed_languages():
    policy = LanguageSwitchPolicy(current="fr", allowed={"fr", "en"})
    assert policy.observe("Hello there my friend", reported_language="en") is None
    # Back to French: the pending English is forgotten.
    assert policy.observe("Oui je suis là merci", reported_language="fr") is None
    assert policy.observe("Thank you so much", reported_language="en") is None
    assert policy.current == "fr"
    # Spanish is not allowed: never a switch, even when strong.
    for _ in range(3):
        assert (
            policy.observe(
                "Quiero hablar con alguien ahora mismo", reported_language="es"
            )
            is None
        )


def test_directive_is_replaced_not_stacked():
    prompt = "Tu es l'agent de Nimbora."
    en = with_language_directive(prompt, language_directive("en"))
    assert en.startswith(prompt) and "speaking English" in en
    es = with_language_directive(en, language_directive("es"))
    assert es.count(DIRECTIVE_HEADER) == 1 and "speaking Spanish" in es
    assert with_language_directive(es, None) == prompt


def test_voice_resolution_order():
    agent_choice = resolve_voice(
        "en",
        provider="speaches",
        overrides={"en": {"voice": "bm_george", "model": "kokoro"}},
    )
    assert (agent_choice.voice, agent_choice.source) == ("bm_george", "agent")
    pack = resolve_voice("sw", provider="speaches")
    assert pack.source == "language_pack" and "piper" in pack.model
    assert resolve_voice("ha", provider="speaches").is_change() is False
    cloud = resolve_voice("de", provider="elevenlabs", service_has_language=True)
    assert (cloud.language, cloud.voice) == ("de", None)
    assert resolve_voice("de", provider="minimax").is_change() is False


class FakeLLM:
    def __init__(self):
        self.updates = []

    async def _update_settings(self, delta: LLMSettings):
        self.updates.append(delta.system_instruction)
        return {"system_instruction": None}


class FakeTTS:
    def __init__(self, *, language=None):
        self._settings = TTSSettings(
            model="kokoro", voice="ff_siwis", language=language
        )
        self.updates = []

    async def _update_settings(self, delta: TTSSettings):
        self.updates.append(delta)
        changed = {}
        for name in ("model", "voice", "language"):
            value = getattr(delta, name)
            if isinstance(value, str):
                setattr(self._settings, name, value)
                changed[name] = True
        return changed


def _engine(provider="speaches", language=None):
    agent = SimpleNamespace(
        llm=FakeLLM(),
        tts=FakeTTS(language=language),
        system_prompt="Tu es l'agent.",
        user_config=SimpleNamespace(
            tts=SimpleNamespace(provider=provider, model="kokoro", voice="ff_siwis")
        ),
    )
    return SimpleNamespace(
        active_agent=agent, _call_context_vars={}, _gathered_context={}
    )


async def test_controller_switches_prompt_voice_and_records_context():
    engine = _engine()
    controller = CallLanguageController(
        engine, default_language="fr", tts_config=engine.active_agent.user_config.tts
    )
    agent = engine.active_agent
    assert await controller.on_transcript("Hello, hear me?", "english") is False
    assert await controller.on_transcript(
        "Yes I want to change my delivery address", "en"
    )
    assert "speaking English" in agent.system_prompt
    assert agent.llm.updates[-1] == agent.system_prompt
    assert agent.tts._settings.voice == "af_heart"  # Kokoro English pack voice
    assert engine._gathered_context["call_language"] == "en"
    assert engine._gathered_context["languages_spoken"] == ["fr", "en"]
    assert engine._call_context_vars["call_language_directive"].startswith(
        DIRECTIVE_HEADER
    )

    # Back to French: French voice (pack default) and French directive.
    await controller.on_transcript("Ah pardon, je préfère parler en français", "fr")
    await controller.on_transcript("Oui c'est mieux pour moi merci", "fr")
    assert controller.current == "fr"
    assert agent.tts._settings.voice == "ff_siwis"
    assert "speaking French" in agent.system_prompt


async def test_cloud_voice_gets_language_and_transfer_agent_follows():
    engine = _engine(provider="elevenlabs", language="fr")
    controller = CallLanguageController(engine, default_language="fr")
    await controller.start_in("de", reason="remembered")
    assert engine.active_agent.tts._settings.language == "de"
    assert engine.active_agent.tts._settings.voice == "ff_siwis"  # same voice

    # A transfer brings a new agent: it adopts the caller's language voice.
    new_agent = _engine(provider="elevenlabs", language="fr").active_agent
    assert await controller.ensure_voice(new_agent) is True
    assert new_agent.tts._settings.language == "de"
    assert await controller.ensure_voice(new_agent) is False  # once only


async def test_start_in_respects_allowed_languages():
    engine = _engine()
    controller = CallLanguageController(engine, default_language="fr", allowed=["en"])
    assert await controller.start_in("es", reason="remembered") is False
    assert await controller.start_in("", reason="remembered") is False
    assert await controller.start_in("en", reason="remembered") is True
    assert controller.history[-1]["reason"] == "remembered"


def test_build_controller_and_schema():
    from api.schemas.workflow_configurations import LanguageDetectionConfiguration

    user_config = SimpleNamespace(
        stt=SimpleNamespace(language="auto"),
        tts=SimpleNamespace(provider="speaches"),
    )
    assert build_controller(SimpleNamespace(), {}, user_config) is None
    controller = build_controller(
        SimpleNamespace(),
        {"language_detection": {"enabled": True, "languages": ["en", "sw"]}},
        user_config,
    )
    assert controller.default_language == "fr"  # STT on auto: fallback
    assert controller.allowed == {"fr", "en", "sw"}
    controller = build_controller(
        SimpleNamespace(),
        {"language_detection": {"enabled": True, "default_language": "en"}},
        user_config,
    )
    assert controller.default_language == "en" and controller.allowed is None

    config = LanguageDetectionConfiguration(
        enabled=True, languages=["FR", " en ", "fr"], voices={"en": {"voice": "x"}}
    )
    assert config.languages == ["fr", "en"]
    with pytest.raises(ValidationError):
        LanguageDetectionConfiguration(languages=["français"])
    with pytest.raises(ValidationError):
        LanguageDetectionConfiguration(voices={"english": {"voice": "x"}})


async def test_speaches_auto_language_tags_transcripts():
    from pipecat.frames.frames import TranscriptionFrame

    from api.services.pipecat.speaches_stt import (
        AutoLanguageSpeachesSTTService,
        is_auto_language,
    )

    assert is_auto_language("auto") and is_auto_language(None)
    assert not is_auto_language("fr")

    stt = AutoLanguageSpeachesSTTService(
        base_url="http://speaches.local/v1",
        settings=AutoLanguageSpeachesSTTService.Settings(model="whisper-large-v3"),
    )
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="Habari yako", language="swahili")

    stt._client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    frames = [f async for f in stt.run_stt(b"\x00" * 320)]
    transcripts = [f for f in frames if isinstance(f, TranscriptionFrame)]
    assert transcripts and transcripts[0].language == "sw"
    assert "language" not in calls[0]
    assert calls[0]["response_format"] == "verbose_json"


def test_prompt_composer_puts_language_last():
    from api.services.workflow.pipecat_engine_context_composer import (
        compose_system_prompt_for_node,
    )

    node = SimpleNamespace(id="n1", prompt="Aide le client.", add_global_prompt=False)
    workflow = SimpleNamespace(global_node_id=None, nodes={"n1": node})
    composed = compose_system_prompt_for_node(
        node=node,
        workflow=workflow,
        format_prompt=lambda text: text,
        has_recordings=False,
        customer_memory="## Mémoire client\n- Nom : Awa",
        language_directive=language_directive("en"),
    )
    assert composed.text.endswith(language_directive("en"))
    assert composed.text.index("Mémoire client") < composed.text.index(DIRECTIVE_HEADER)

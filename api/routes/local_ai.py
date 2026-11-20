"""Languages and voices available on the platform's self-hosted AI stack."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.constants import (
    LOCAL_AI_ENABLED,
    LOCAL_DEFAULT_LANGUAGE,
    LOCAL_LLM_MODEL,
    LOCAL_STT_MODEL,
)
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.local_ai.language_packs import LANGUAGE_PACKS, WHISPER_LANGUAGES

router = APIRouter(prefix="/local-ai", tags=["local-ai"])


class VoiceOut(BaseModel):
    model: str
    voice: str
    label: str
    gender: str


class LanguageOut(BaseModel):
    code: str
    name: str
    stt_language: str
    voices: list[VoiceOut]
    note: str


class LocalAIInfo(BaseModel):
    enabled: bool
    default_language: str
    llm_model: str
    stt_model: str
    languages: list[LanguageOut]
    stt_languages: list[str]


@router.get("/languages", response_model=LocalAIInfo)
async def list_local_languages(_: UserModel = Depends(get_user)):
    return LocalAIInfo(
        enabled=LOCAL_AI_ENABLED,
        default_language=LOCAL_DEFAULT_LANGUAGE,
        llm_model=LOCAL_LLM_MODEL,
        stt_model=LOCAL_STT_MODEL,
        languages=[
            LanguageOut(
                code=pack.code,
                name=pack.name,
                stt_language=pack.whisper_language,
                voices=[VoiceOut(**vars(v)) for v in pack.voices],
                note=pack.note,
            )
            for pack in LANGUAGE_PACKS.values()
        ],
        stt_languages=list(WHISPER_LANGUAGES),
    )

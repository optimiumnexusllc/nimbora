"""Azure authentication and transport with NIMBORA's OpenAI realtime behavior."""

from api.services.pipecat.realtime.openai_realtime import (
    NimboraOpenAIRealtimeLLMService,
)
from pipecat.services.azure.realtime.llm import AzureRealtimeLLMService


class NimboraAzureRealtimeLLMService(
    NimboraOpenAIRealtimeLLMService, AzureRealtimeLLMService
):
    """Share OpenAI conversation handling while retaining Azure's constructor."""

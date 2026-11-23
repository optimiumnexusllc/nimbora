"""The company's own language model, for out-of-call text exchanges.

Agent tests play the agent, the simulated customer and the judge with the
model configured in « Modèles IA » (never a hosted-only key). OpenAI-compatible
providers (OpenAI, Groq, OpenRouter, Azure, Together, Mistral, …) are called
with native tool calling, exactly like a live call; others (Google, Anthropic,
…) get the tools described in the prompt and answer in JSON — noted in the
test result, since the agent's tool choices are then approximated.
"""

import asyncio
import json
import re
import uuid
from typing import Any

from loguru import logger

USAGE_CONTEXT = "agent_tests"
TIMEOUT_SECONDS = 60


class ModelUnavailable(Exception):
    """No language model is configured for the company."""


class OrgChatModel:
    def __init__(self, organization_id: int):
        self.organization_id = organization_id
        self._llm = None
        self.native_tools: bool | None = None

    async def _service(self):
        if self._llm is None:
            from fastapi import HTTPException

            from api.services.configuration.model_connections import (
                resolve_model_configuration,
            )
            from api.services.pipecat.service_factory import create_llm_service

            try:
                resolved = await resolve_model_configuration(self.organization_id)
            except HTTPException as error:
                raise ModelUnavailable(
                    "Aucun modèle de langage utilisable : vérifiez-le dans Modèles IA "
                    f"({error.detail})"
                ) from error
            if resolved.effective.llm is None:
                raise ModelUnavailable(
                    "Aucun modèle de langage configuré : renseignez-le dans Modèles IA"
                )
            self._llm = create_llm_service(
                resolved.effective, usage_context=USAGE_CONTEXT, spoken_output=False
            )
        return self._llm

    def _openai(self, llm):
        from pipecat.services.openai.base_llm import BaseOpenAILLMService

        from api.services.pipecat.fallback_llm import FallbackLLMProcessor

        primary = llm.processors[0] if isinstance(llm, FallbackLLMProcessor) else llm
        return primary if isinstance(primary, BaseOpenAILLMService) else None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        """``{"content": str, "tool_calls": [{"id", "name", "args"}]}``.

        ``messages`` use the OpenAI chat format (system, user, assistant with
        tool_calls, tool).
        """
        llm = await self._service()
        openai = self._openai(llm)
        self.native_tools = openai is not None
        wire = ([{"role": "system", "content": system}] if system else []) + messages
        async with asyncio.timeout(TIMEOUT_SECONDS):
            if openai is not None:
                params: dict[str, Any] = {
                    "model": openai._settings.model,
                    "messages": wire,
                }
                if tools:
                    params["tools"] = tools
                response = await openai._client.chat.completions.create(**params)
                message = response.choices[0].message
                calls = []
                for call in message.tool_calls or []:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {"_invalid_json": call.function.arguments}
                    calls.append(
                        {"id": call.id, "name": call.function.name, "args": args}
                    )
                return {"content": message.content or "", "tool_calls": calls}
            return await self._json_fallback(llm, wire, tools)

    async def _json_fallback(self, llm, wire, tools) -> dict[str, Any]:
        from pipecat.processors.aggregators.llm_context import LLMContext

        system = "\n\n".join(m["content"] for m in wire if m["role"] == "system")
        lines = []
        for m in wire:
            if m["role"] == "user":
                lines.append(f"INTERLOCUTEUR : {m['content']}")
            elif m["role"] == "assistant":
                if m.get("content"):
                    lines.append(f"TOI : {m['content']}")
                for call in m.get("tool_calls") or []:
                    lines.append(
                        f"TOI (action) : {call['function']['name']} "
                        f"{call['function']['arguments']}"
                    )
            elif m["role"] == "tool":
                lines.append(f"RÉSULTAT DE L'ACTION : {m['content']}")
        instructions = ""
        if tools:
            described = json.dumps([t["function"] for t in tools], ensure_ascii=False)
            instructions = (
                "\n\nActions disponibles (fonctions) :\n"
                f"{described}\n\nRéponds UNIQUEMENT en JSON : "
                '{"say": "ce que tu dis (peut être vide)", "tool_calls": '
                '[{"name": "...", "arguments": {...}}]}'
            )
        context = LLMContext(
            messages=[{"role": "user", "content": "\n".join(lines) + instructions}]
        )
        raw = await llm.run_inference(context, system_instruction=system or None)
        if not tools:
            return {"content": raw or "", "tool_calls": []}
        match = re.search(r"\{.*\}", raw or "", re.S)
        try:
            data = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        calls = [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "name": str(c.get("name")),
                "args": c.get("arguments")
                if isinstance(c.get("arguments"), dict)
                else {},
            }
            for c in data.get("tool_calls") or []
            if isinstance(c, dict) and c.get("name")
        ]
        say = data.get("say") if data else raw
        return {"content": str(say or ""), "tool_calls": calls}

    async def close(self) -> None:
        if self._llm is None:
            return
        from pipecat.services.openai.base_llm import BaseOpenAILLMService

        from api.services.pipecat.fallback_llm import FallbackLLMProcessor

        llm = self._llm
        processors = llm.processors if isinstance(llm, FallbackLLMProcessor) else [llm]
        for processor in processors:
            if isinstance(processor, BaseOpenAILLMService):
                try:
                    async with asyncio.timeout(5):
                        await processor._client.close()
                except Exception:  # noqa: BLE001 - best effort cleanup
                    logger.debug("Agent test model client not closed")
        self._llm = None

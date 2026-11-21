"""What a supervisor can do to a live AI call (runs on the call's worker).

* ``instruct`` — whisper an instruction to the AI: it joins the system prompt
  in a "Supervisor instructions" section (kept for the rest of the call,
  across nodes) — the caller hears nothing;
* ``say`` — the agent says a sentence now, verbatim, then carries on;
* ``takeover`` — transfer the caller to a contact-center queue, exactly like
  the agent's own transfer tool (AI handoff card included);
* ``hangup`` — end the call politely after an optional last sentence.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

SECTION_HEADER = "## Supervisor instructions"
MAX_INSTRUCTIONS = 10


def with_supervisor_section(prompt: str, instructions: list[str]) -> str:
    """Put the supervisor section before any language section (which must
    stay last), replacing a previous one."""
    from api.services.language.detection import DIRECTIVE_HEADER

    base = prompt or ""
    language = ""
    marker = base.find(DIRECTIVE_HEADER)
    if marker != -1:
        base, language = base[:marker].rstrip(), base[marker:]
    start = base.find(SECTION_HEADER)
    if start != -1:
        base = base[:start].rstrip()
    parts = [base] if base else []
    if instructions:
        lines = "\n".join(f"- {text}" for text in instructions)
        parts.append(
            f"{SECTION_HEADER}\n"
            "A human supervisor is following this call and gave these "
            "instructions. Apply them from your next reply on, naturally, "
            "without mentioning the supervisor:\n" + lines
        )
    if language:
        parts.append(language)
    return "\n\n".join(parts)


class SupervisorActions:
    def __init__(self, engine: Any):
        self._engine = engine
        self.instructions: list[str] = []

    def register(self, publisher) -> None:
        publisher.on_command("instruct", self.instruct)
        publisher.on_command("say", self.say)
        publisher.on_command("takeover", self.takeover)
        publisher.on_command("hangup", self.hangup)

    async def instruct(self, command: dict) -> dict:
        text = str(command.get("text") or "").strip()[:500]
        if not text:
            return {"status": "error", "error": "empty instruction"}
        self.instructions = (self.instructions + [text])[-MAX_INSTRUCTIONS:]
        agent = getattr(self._engine, "active_agent", None)
        if agent is None or getattr(agent, "llm", None) is None:
            return {"status": "error", "error": "no active agent"}
        updated = with_supervisor_section(agent.system_prompt or "", self.instructions)
        agent.system_prompt = updated
        from pipecat.services.settings import LLMSettings

        await agent.llm._update_settings(LLMSettings(system_instruction=updated))
        context_vars = getattr(self._engine, "_call_context_vars", None)
        if isinstance(context_vars, dict):
            # Kept when the call moves to another node (prompt recomposed).
            context_vars["supervisor_instructions"] = list(self.instructions)
        return {"status": "ok"}

    async def say(self, command: dict) -> dict:
        text = str(command.get("text") or "").strip()[:500]
        if not text:
            return {"status": "error", "error": "empty message"}
        queued = await self._engine.queue_text_message(text, append_to_context=True)
        return {"status": "ok" if queued else "error"}

    async def takeover(self, command: dict) -> dict:
        slug = str(command.get("queue_slug") or "").strip()
        if not slug:
            return {"status": "error", "error": "queue_slug is required"}
        from api.services.workflow.pipecat_engine_custom_tools import CustomToolManager

        manager = getattr(
            self._engine, "_custom_tool_manager", None
        ) or CustomToolManager(self._engine)
        tool = SimpleNamespace(
            name="supervisor_takeover",
            tool_uuid="supervisor-takeover",
            category="transfer_call",
            definition={
                "type": "transfer_call",
                "config": {"destination": f"queue:{slug}", "timeout": 30},
                "messages": [],
            },
        )
        handler = manager._create_transfer_call_handler(tool, "supervisor_takeover")
        results: list[dict] = []

        async def result_callback(result, properties=None):
            results.append(result if isinstance(result, dict) else {"result": result})

        params = SimpleNamespace(
            function_name="supervisor_takeover",
            tool_call_id="supervisor-takeover",
            arguments={},
            llm=getattr(getattr(self._engine, "active_agent", None), "llm", None),
            context=getattr(self._engine, "context", None),
            result_callback=result_callback,
        )
        message = str(command.get("text") or "").strip()
        if message:
            await self._engine.queue_text_message(message, append_to_context=True)
        await handler(params)
        outcome = results[-1] if results else {}
        failed = str(outcome.get("status", "")).lower() in {"failed", "error"}
        if failed:
            logger.warning(f"Supervisor takeover failed: {outcome}")
            return {
                "status": "error",
                "error": outcome.get("reason") or outcome.get("message"),
            }
        return {"status": "ok"}

    async def hangup(self, command: dict) -> dict:
        from pipecat.utils.enums import EndTaskReason

        text = str(command.get("text") or "").strip()[:300]
        if text:
            speech = await self._engine.queue_speech(text)
            if speech is not None:
                await speech.wait()
        self._engine.set_call_disposition("supervisor_hangup")
        await self._engine.end_call_with_reason(EndTaskReason.END_CALL.value)
        return {"status": "ok"}

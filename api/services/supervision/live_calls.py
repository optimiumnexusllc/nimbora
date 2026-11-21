"""Live AI calls, visible and steerable by supervisors from any server.

Calls run on whichever worker picked them up; supervisors' browsers talk to
any API instance. Redis ties them together:

* ``nimbora:live:org:{org}`` (hash) — one entry per call in progress: agent,
  caller, direction, start time, last words, state. Refreshed by a heartbeat;
  readers drop entries whose heartbeat is older than ``STALE_AFTER``.
* ``nimbora:live:run:{run}:events`` (list) — the call's live feed (caller
  and agent speech, tools, node changes, supervisor actions), each event with
  a sequence number so the UI polls "everything after #n".
* ``nimbora:live:cmd:{run}`` (pub/sub) — supervisor commands to the worker
  holding the call: whisper an instruction to the AI, take over (transfer to
  a human queue), hang up.

Everything is best effort: Redis trouble never disturbs a call.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

ORG_KEY = "nimbora:live:org:{org}"
EVENTS_KEY = "nimbora:live:run:{run}:events"
SEQ_KEY = "nimbora:live:run:{run}:seq"
CMD_CHANNEL = "nimbora:live:cmd:{run}"
MAX_EVENTS = 400
EVENTS_TTL_SECONDS = 2 * 3600
HEARTBEAT_SECONDS = 10
STALE_AFTER = 45

# Feed events kept for supervisors (metrics and mute toggles are noise here).
_FEED_TYPES = {
    "rtf-user-transcription": "caller",
    "rtf-bot-text": "agent",
    "rtf-function-call-start": "tool",
    "rtf-function-call-end": "tool_result",
    "rtf-node-transition": "node",
    "rtf-bot-started-speaking": "agent_speaking",
    "rtf-bot-stopped-speaking": "agent_silent",
    "rtf-pipeline-error": "error",
}

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis
        from api.constants import REDIS_URL

        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def feed_event(message: dict[str, Any]) -> dict[str, Any] | None:
    """Turn a realtime-feedback message into a compact supervisor event."""
    kind = _FEED_TYPES.get(str(message.get("type")))
    if kind is None:
        return None
    payload = message.get("payload") or {}
    event: dict[str, Any] = {"kind": kind, "at": round(time.time(), 2)}
    if kind == "caller":
        if not payload.get("final", True):
            return None  # interim results would flood the feed
        event["text"] = payload.get("text") or ""
    elif kind == "agent":
        event["text"] = payload.get("text") or ""
    elif kind in {"tool", "tool_result"}:
        event["name"] = payload.get("function_name") or payload.get("name")
    elif kind == "node":
        event["name"] = payload.get("node_name") or message.get("node_name")
    elif kind == "error":
        event["text"] = str(payload.get("error") or "")[:300]
    if kind in {"caller", "agent"} and not event["text"].strip():
        return None
    return event


class LiveCallPublisher:
    """Owned by one running call: publishes its state and feed, listens for
    supervisor commands."""

    def __init__(
        self,
        *,
        organization_id: int,
        run_id: int,
        meta: dict[str, Any],
        redis_factory: Callable[[], Awaitable[Any]] = get_redis,
    ):
        self.organization_id = organization_id
        self.run_id = run_id
        self.meta = {
            "run_id": run_id,
            "started_at": round(time.time(), 2),
            "state": "starting",
            "last_caller_text": "",
            "last_agent_text": "",
            "turns": 0,
            **meta,
        }
        self._redis_factory = redis_factory
        self._tasks: list[asyncio.Task] = []
        self._handlers: dict[str, Callable[[dict], Awaitable[dict]]] = {}
        self._agent_buffer = ""
        self._closed = False

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self._write_meta()
        await self.add_event({"kind": "started", "at": self.meta["started_at"]})
        self._tasks.append(
            asyncio.create_task(self._heartbeat(), name="live-heartbeat")
        )
        self._tasks.append(asyncio.create_task(self._listen(), name="live-commands"))
        await self._notify_consoles()

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            task.cancel()
        try:
            await self.add_event({"kind": "ended", "at": round(time.time(), 2)})
            redis = await self._redis_factory()
            await redis.hdel(ORG_KEY.format(org=self.organization_id), str(self.run_id))
        except Exception:
            logger.opt(exception=True).debug("Live call cleanup failed")
        await self._notify_consoles()

    async def _notify_consoles(self) -> None:
        from api.services.supervision.stream import notify

        await notify(self.organization_id, "ai")

    def on_command(self, name: str, handler: Callable[[dict], Awaitable[dict]]) -> None:
        self._handlers[name] = handler

    # ------------------------------------------------------------- publishing
    def wrap_sender(self, sender: Callable[[dict], Awaitable[None]] | None):
        """Tee the realtime-feedback stream into the supervisor feed."""

        async def tee(message: dict) -> None:
            if sender is not None:
                await sender(message)
            await self.observe(message)

        return tee

    async def observe(self, message: dict[str, Any]) -> None:
        event = feed_event(message)
        if event is None:
            return
        kind = event["kind"]
        if kind == "caller":
            self.meta["last_caller_text"] = event["text"][-240:]
            self.meta["state"] = "caller_speaking"
            self.meta["turns"] += 1
        elif kind == "agent":
            # Agent text arrives in chunks; the feed keeps chunks, the card
            # keeps the current sentence.
            self._agent_buffer = (self._agent_buffer + " " + event["text"]).strip()[
                -240:
            ]
            self.meta["last_agent_text"] = self._agent_buffer
        elif kind == "agent_speaking":
            self.meta["state"] = "agent_speaking"
            self._agent_buffer = ""
        elif kind == "agent_silent":
            self.meta["state"] = "listening"
        elif kind == "node":
            self.meta["node"] = event.get("name")
        if kind in {"agent_speaking", "agent_silent"}:
            await self._write_meta()
            return
        await self.add_event(event)
        await self._write_meta()

    def update_meta(self, **fields: Any) -> None:
        self.meta.update(fields)

    async def add_event(self, event: dict[str, Any]) -> None:
        try:
            redis = await self._redis_factory()
            seq = await redis.incr(SEQ_KEY.format(run=self.run_id))
            key = EVENTS_KEY.format(run=self.run_id)
            await redis.rpush(key, json.dumps({**event, "seq": seq}))
            await redis.ltrim(key, -MAX_EVENTS, -1)
            await redis.expire(key, EVENTS_TTL_SECONDS)
            await redis.expire(SEQ_KEY.format(run=self.run_id), EVENTS_TTL_SECONDS)
        except Exception:
            logger.opt(exception=True).debug("Live call event not published")

    async def _write_meta(self) -> None:
        if self._closed:
            return
        try:
            redis = await self._redis_factory()
            self.meta["heartbeat_at"] = round(time.time(), 2)
            await redis.hset(
                ORG_KEY.format(org=self.organization_id),
                str(self.run_id),
                json.dumps(self.meta, default=str),
            )
        except Exception:
            logger.opt(exception=True).debug("Live call state not published")

    async def _heartbeat(self) -> None:
        while not self._closed:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self._write_meta()

    # --------------------------------------------------------------- commands
    async def _listen(self) -> None:
        try:
            redis = await self._redis_factory()
            pubsub = redis.pubsub()
            await pubsub.subscribe(CMD_CHANNEL.format(run=self.run_id))
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    await self.handle_command(message.get("data"))
            finally:
                await pubsub.unsubscribe()
                await pubsub.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).debug("Live call command listener stopped")

    async def handle_command(self, raw: Any) -> dict:
        try:
            command = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError):
            return {"status": "error", "error": "malformed command"}
        name = command.get("action")
        handler = self._handlers.get(str(name))
        if handler is None:
            result = {"status": "error", "error": f"unsupported action {name}"}
        else:
            try:
                result = await handler(command)
            except Exception as exc:
                logger.opt(exception=True).warning(f"Supervisor action {name} failed")
                result = {"status": "error", "error": str(exc)[:200]}
        await self.add_event(
            {
                "kind": "supervisor",
                "action": name,
                "by": command.get("by"),
                "text": command.get("text"),
                "status": result.get("status"),
                "error": result.get("error"),
                "at": round(time.time(), 2),
            }
        )
        return result


# ------------------------------------------------------------ reading side


async def list_live_calls(
    organization_id: int, *, now: float | None = None
) -> list[dict]:
    redis = await get_redis()
    now = now or time.time()
    raw = await redis.hgetall(ORG_KEY.format(org=organization_id))
    calls, stale = [], []
    for run_id, value in raw.items():
        try:
            meta = json.loads(value)
        except ValueError:
            stale.append(run_id)
            continue
        if now - float(meta.get("heartbeat_at") or 0) > STALE_AFTER:
            stale.append(run_id)  # worker died without cleaning up
            continue
        meta["duration_seconds"] = int(now - float(meta.get("started_at") or now))
        calls.append(meta)
    if stale:
        await redis.hdel(ORG_KEY.format(org=organization_id), *stale)
    return sorted(calls, key=lambda c: c.get("started_at") or 0)


async def is_live(organization_id: int, run_id: int) -> bool:
    redis = await get_redis()
    return bool(await redis.hexists(ORG_KEY.format(org=organization_id), str(run_id)))


async def read_events(run_id: int, after: int = 0) -> list[dict]:
    redis = await get_redis()
    events = []
    for raw in await redis.lrange(EVENTS_KEY.format(run=run_id), 0, -1):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if int(event.get("seq") or 0) > after:
            events.append(event)
    return events


async def send_command(run_id: int, command: dict[str, Any]) -> int:
    """Publish a command; returns how many workers received it (0 = call gone)."""
    redis = await get_redis()
    return int(await redis.publish(CMD_CHANNEL.format(run=run_id), json.dumps(command)))

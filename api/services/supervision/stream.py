"""Real-time supervision: one WebSocket per console instead of polling.

Whatever changes the picture publishes a small notice on
``nimbora:supervision:org:{org}`` (Redis pub/sub, so it reaches the API
worker holding the supervisor's socket):

* the PBX webhook (calls created, answered, updated, ended; agents logging
  in, pausing; call logs) → ``{"source": "pbx", "at": t}``;
* AI calls starting and ending → ``{"source": "ai"}``.

Each socket then rebuilds the view and sends it only if it changed. Ticks
still run without notices — AI transcripts every few seconds, the PBX every
``PBX_REFRESH_SECONDS`` — so the view stays right if webhooks are not
delivered. Everything is best effort: Redis trouble falls back to ticks.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger

from api.services.supervision.live_calls import get_redis

CHANNEL = "nimbora:supervision:org:{org}"
AI_REFRESH_SECONDS = 3.0
PBX_REFRESH_SECONDS = 10.0
PING_SECONDS = 25.0
DEBOUNCE_SECONDS = 0.3


async def notify(organization_id: int, source: str) -> None:
    """Tell the organization's open consoles that something changed."""
    try:
        redis = await get_redis()
        await redis.publish(
            CHANNEL.format(org=organization_id),
            json.dumps({"source": source, "at": time.time()}),
        )
    except Exception:  # noqa: BLE001 - consoles fall back to their ticks
        logger.opt(exception=True).debug("Supervision notice not published")


async def ai_view(organization_id: int, user_id: int) -> dict[str, Any]:
    from api.services.supervision import overview

    return await overview.snapshot(organization_id, user_id)


async def pbx_view(
    organization_id: int, newer_than: float | None = None
) -> dict[str, Any] | None:
    """The PBX side, or None when the organization has no PBX connected."""
    from api.services.pbx import supervision
    from api.services.pbx.client import PbxError
    from api.services.pbx.service import PbxNotConfigured

    try:
        return await supervision.live(organization_id, newer_than=newer_than)
    except PbxNotConfigured:
        return None
    except PbxError as error:
        return {"unavailable": str(error)}


# Counters the console advances on its own: a change of these alone is not
# worth a message (the next real change re-synchronizes the clocks).
_CLOCKS = frozenset(
    {"at", "seconds", "wait_seconds", "longest_wait_seconds", "duration_seconds"}
)


def _without_clocks(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_clocks(v) for k, v in value.items() if k not in _CLOCKS}
    if isinstance(value, list):
        return [_without_clocks(v) for v in value]
    return value


def _comparable(view: Any) -> str:
    """The view without running clocks, to send only real changes."""
    return json.dumps(_without_clocks(view), sort_keys=True, default=str)


class _Notices:
    """Pub/sub subscription feeding a queue; silent if Redis is unavailable."""

    def __init__(self, organization_id: int):
        self.channel = CHANNEL.format(org=organization_id)
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self._pubsub = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            redis = await get_redis()
            self._pubsub = redis.pubsub()
            await self._pubsub.subscribe(self.channel)
            self._task = asyncio.create_task(self._read(), name="supervision-notices")
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).debug("Supervision notices unavailable")

    async def _read(self) -> None:
        try:
            async for message in self._pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    self.queue.put_nowait(json.loads(message["data"]))
                except (TypeError, ValueError):
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).debug("Supervision notices stopped")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(self.channel)
                await self._pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass


async def run(websocket, organization_id: int, user_id: int) -> None:
    """Serve one console until it disconnects."""
    notices = _Notices(organization_id)
    await notices.start()
    sent: dict[str, str] = {}
    last = {"ai": 0.0, "pbx": 0.0, "ping": time.monotonic()}
    requests: asyncio.Queue[str] = asyncio.Queue()

    async def receive() -> None:
        # The console may ask for a refresh ({"type": "refresh"}).
        while True:
            message = await websocket.receive_text()
            try:
                if json.loads(message).get("type") == "refresh":
                    requests.put_nowait("refresh")
            except (TypeError, ValueError, AttributeError):
                continue

    async def send(part: str, view: Any) -> None:
        key = _comparable(view)
        if sent.get(part) == key:
            return
        sent[part] = key
        await websocket.send_json({"type": part, "data": view})

    receiver = asyncio.create_task(receive(), name="supervision-receive")
    try:
        await send("ai", await ai_view(organization_id, user_id))
        await send("pbx", await pbx_view(organization_id))
        last["ai"] = last["pbx"] = time.monotonic()
        while not receiver.done():
            notice = None
            refresh = False
            try:
                waiters = [
                    asyncio.ensure_future(notices.queue.get()),
                    asyncio.ensure_future(requests.get()),
                ]
                done, pending = await asyncio.wait(
                    waiters + [receiver],
                    timeout=1.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    if task is not receiver:
                        task.cancel()
                for task in done:
                    if task is receiver:
                        continue
                    result = task.result()
                    if result == "refresh":
                        refresh = True
                    else:
                        notice = result
            except asyncio.CancelledError:
                raise
            if receiver.done():
                break
            if notice is not None:
                await asyncio.sleep(DEBOUNCE_SECONDS)  # let a burst settle
                while not notices.queue.empty():
                    notices.queue.get_nowait()
            now = time.monotonic()
            source = (notice or {}).get("source")
            if refresh or source == "ai" or now - last["ai"] >= AI_REFRESH_SECONDS:
                await send("ai", await ai_view(organization_id, user_id))
                last["ai"] = now
            if refresh or source == "pbx" or now - last["pbx"] >= PBX_REFRESH_SECONDS:
                newer = (notice or {}).get("at") if source == "pbx" else None
                if refresh:
                    newer = time.time()
                await send("pbx", await pbx_view(organization_id, newer_than=newer))
                last["pbx"] = now
            if now - last["ping"] >= PING_SECONDS:
                await websocket.send_json({"type": "ping"})
                last["ping"] = now
    finally:
        receiver.cancel()
        await notices.stop()

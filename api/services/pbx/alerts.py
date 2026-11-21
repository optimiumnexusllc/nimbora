"""Supervision alerts on the enterprise PBX: nobody should wait unnoticed.

Rules, per company (in ``supervision_settings["alerts"]``):

* **long wait** — a caller has waited longer than ``max_wait_seconds``;
* **queue full** — more than ``max_waiting`` callers in one queue;
* **no agent** — callers are waiting and no agent of that queue is available.

The console evaluates them on every live update (banner, browser
notification, wall display). A worker job (every minute) evaluates them too
and tells people who are not looking at a screen: a webhook (Slack, Teams,
Google Chat, n8n… — ``{"text": …}``) and/or e-mail through one of the
company's own e-mail tools. A notification goes out when an alert starts and
when it ends ("rétabli"), never twice for the same alert within
``cooldown_minutes``.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from api.services.pbx.service import PbxRouteError, _connection

KINDS = ("long_wait", "queue_full", "no_agent")
STATE_KEY = "nimbora:pbx:alerts:{org}"
LOG_KEY = "nimbora:pbx:alerts:log:{org}"
LOG_SIZE = 100
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "max_wait_seconds": 120,
    "max_waiting": 5,
    "no_agent": True,
    "queue_ids": [],  # empty: every queue
    "webhook_url": "",
    "email_tool_uuid": None,
    "email_recipients": [],
    "cooldown_minutes": 15,
}


def read_settings(connection) -> dict[str, Any]:
    stored = (connection.supervision_settings or {}).get("alerts") or {}
    return {**DEFAULTS, **stored}


async def save_settings(
    organization_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    from api.db import db_client
    from api.services.actions.common import ActionError, check_outbound_url

    connection = await _connection(organization_id)
    settings = {**read_settings(connection), **payload}
    if not 10 <= int(settings["max_wait_seconds"]) <= 3600:
        raise PbxRouteError("L'attente maximale va de 10 s à 1 h.", 422)
    if not 1 <= int(settings["max_waiting"]) <= 200:
        raise PbxRouteError("Le nombre d'appelants va de 1 à 200.", 422)
    if not 1 <= int(settings["cooldown_minutes"]) <= 1440:
        raise PbxRouteError("Le délai entre deux alertes va de 1 à 1 440 minutes.", 422)
    url = (settings.get("webhook_url") or "").strip()
    if url:
        if not url.startswith("https://"):
            raise PbxRouteError("L'adresse du webhook doit commencer par https://", 422)
        try:
            check_outbound_url(url, "webhook_url")
        except ActionError as error:
            raise PbxRouteError(str(error), 422) from error
    settings["webhook_url"] = url
    recipients = [
        r.strip() for r in settings.get("email_recipients") or [] if r.strip()
    ]
    settings["email_recipients"] = recipients[:20]
    if settings.get("email_tool_uuid"):
        await _email_tool(organization_id, settings["email_tool_uuid"])
    elif recipients:
        raise PbxRouteError("Choisissez l'outil e-mail qui enverra les alertes.", 422)
    supervision = dict(connection.supervision_settings or {})
    supervision["alerts"] = settings
    await db_client.save_pbx_connection(
        organization_id, {"supervision_settings": supervision}
    )
    return settings


# --------------------------------------------------------------- evaluation


def _callers(count: int) -> str:
    return f"{count} appelant" + ("s" if count > 1 else "")


def _duration(seconds: int) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min {rest:02d} s" if minutes else f"{rest} s"


def evaluate(live: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The alerts the live state raises right now (most serious first)."""
    if not settings.get("enabled"):
        return []
    wanted = set(settings.get("queue_ids") or [])
    alerts: list[dict[str, Any]] = []
    for queue in live.get("queues") or []:
        if wanted and queue.get("id") not in wanted:
            continue
        if not queue.get("live") or not queue.get("waiting"):
            continue
        name = queue.get("name") or f"File {queue.get('id')}"
        base = {"queue_id": queue.get("id"), "queue_name": name}
        waiting = int(queue["waiting"])
        longest = int(queue.get("longest_wait_seconds") or 0)
        if settings.get("no_agent") and not queue.get("agents_available"):
            nobody_logged = not queue.get("agents_logged")
            alerts.append(
                {
                    **base,
                    "kind": "no_agent",
                    "level": "critical",
                    "value": waiting,
                    "message": f"{name} : {_callers(waiting)} en attente et "
                    + (
                        "aucun conseiller connecté"
                        if nobody_logged
                        else "aucun conseiller disponible"
                    ),
                }
            )
        if longest > int(settings["max_wait_seconds"]):
            alerts.append(
                {
                    **base,
                    "kind": "long_wait",
                    "level": "critical"
                    if longest > 2 * int(settings["max_wait_seconds"])
                    else "warning",
                    "value": longest,
                    "message": f"{name} : un client attend depuis {_duration(longest)} "
                    f"(seuil {_duration(int(settings['max_wait_seconds']))})",
                }
            )
        if waiting > int(settings["max_waiting"]):
            alerts.append(
                {
                    **base,
                    "kind": "queue_full",
                    "level": "warning",
                    "value": waiting,
                    "message": f"{name} : {waiting} appelants en attente (seuil {settings['max_waiting']})",
                }
            )
    for alert in alerts:
        alert["key"] = f"{alert['kind']}:{alert['queue_id']}"
    order = {"critical": 0, "warning": 1}
    return sorted(
        alerts,
        key=lambda a: (
            order[a["level"]],
            a["queue_name"] or "",
            KINDS.index(a["kind"]),
        ),
    )


# ------------------------------------------------------------ notifications


async def _email_tool(organization_id: int, tool_uuid: str):
    from api.db import db_client

    tool = await db_client.get_tool_by_uuid(str(tool_uuid), organization_id)
    config = ((tool.definition or {}).get("config") or {}) if tool else {}
    if (
        tool is None
        or tool.category != "send_message"
        or config.get("channel") != "email"
        or (config.get("provider") or "") != "smtp"
    ):
        raise PbxRouteError(
            "Choisissez un outil « message » e-mail (SMTP) de l'entreprise.", 422
        )
    return config


async def _post_webhook(url: str, text: str, payload: dict[str, Any]) -> None:
    from api.services.actions.common import check_outbound_url

    check_outbound_url(url, "webhook_url")  # re-checked: DNS may have changed
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(url, json={"text": text, "alert": payload})
        response.raise_for_status()


async def _send_emails(
    organization_id: int, settings: dict[str, Any], subject: str, body: str
) -> None:
    from api.services.actions.common import load_credential
    from api.services.actions.messaging import send_email

    config = await _email_tool(organization_id, settings["email_tool_uuid"])
    credential = await load_credential(organization_id, config.get("credential_uuid"))
    for recipient in settings.get("email_recipients") or []:
        await send_email(config, credential, recipient, subject, body)


async def notify(
    organization_id: int, settings: dict[str, Any], text: str, payload: dict[str, Any]
) -> dict[str, str]:
    """Send one message on every configured channel. Returns channel → outcome."""
    from api.services.branding import brand

    outcome: dict[str, str] = {}
    if settings.get("webhook_url"):
        try:
            await _post_webhook(settings["webhook_url"], text, payload)
            outcome["webhook"] = "sent"
        except Exception as error:  # noqa: BLE001 - one channel never blocks another
            logger.opt(exception=True).warning("Supervision alert webhook failed")
            outcome["webhook"] = f"failed: {error}"[:200]
    if settings.get("email_tool_uuid") and settings.get("email_recipients"):
        try:
            await _send_emails(
                organization_id,
                settings,
                f"[{brand().name}] {text}"[:200],
                text
                + "\n\nSupervision en direct : ouvrez la console, onglet Supervision.",
            )
            outcome["email"] = "sent"
        except Exception as error:  # noqa: BLE001
            logger.opt(exception=True).warning("Supervision alert e-mail failed")
            outcome["email"] = f"failed: {error}"[:200]
    return outcome


async def _log(organization_id: int, entry: dict[str, Any]) -> None:
    from api.services.supervision.live_calls import get_redis

    redis = await get_redis()
    key = LOG_KEY.format(org=organization_id)
    await redis.lpush(key, json.dumps(entry, default=str))
    await redis.ltrim(key, 0, LOG_SIZE - 1)


async def recent_log(organization_id: int, limit: int = 30) -> list[dict[str, Any]]:
    from api.services.supervision.live_calls import get_redis

    redis = await get_redis()
    raw = await redis.lrange(LOG_KEY.format(org=organization_id), 0, limit - 1)
    return [json.loads(item) for item in raw]


async def check_organization(
    organization_id: int, now: float | None = None
) -> dict[str, int]:
    """Compare the live alerts with the last check; notify starts and ends."""
    from api.services.pbx import supervision
    from api.services.supervision.live_calls import get_redis

    now = now or time.time()
    connection = await _connection(organization_id)
    settings = read_settings(connection)
    redis = await get_redis()
    state_key = STATE_KEY.format(org=organization_id)
    previous = {k: json.loads(v) for k, v in (await redis.hgetall(state_key)).items()}
    current = (
        {
            a["key"]: a
            for a in evaluate(await supervision.live(organization_id), settings)
        }
        if settings["enabled"]
        else {}
    )
    cooldown = int(settings["cooldown_minutes"]) * 60
    counts = {"raised": 0, "cleared": 0}

    for key, alert in current.items():
        known = previous.get(key)
        if known and known.get("active"):
            continue
        if known and now - float(known.get("notified_at") or 0) < cooldown:
            # Flapping: back within the cooldown, active again but not re-sent.
            await redis.hset(
                state_key, key, json.dumps({**known, "active": True, "silent": True})
            )
            continue
        outcome = await notify(
            organization_id,
            settings,
            f"⚠️ {alert['message']}",
            {"event": "alert", **alert},
        )
        await redis.hset(
            state_key,
            key,
            json.dumps(
                {
                    "active": True,
                    "since": now,
                    "notified_at": now,
                    "message": alert["message"],
                }
            ),
        )
        await _log(
            organization_id,
            {
                "at": datetime.fromtimestamp(now, UTC).isoformat(),
                "event": "alert",
                **alert,
                "channels": outcome,
            },
        )
        counts["raised"] += 1

    for key, known in previous.items():
        if key in current:
            continue
        if not known.get("active"):
            if now - float(known.get("notified_at") or 0) >= cooldown:
                await redis.hdel(state_key, key)  # forgotten after the cooldown
            continue
        await redis.hset(
            state_key, key, json.dumps({**known, "active": False, "silent": False})
        )
        if known.get("silent"):
            continue  # its return was never sent: neither is its end
        text = f"✅ Rétabli — {known.get('message') or key}"
        outcome = await notify(
            organization_id, settings, text, {"event": "resolved", "key": key}
        )
        await _log(
            organization_id,
            {
                "at": datetime.fromtimestamp(now, UTC).isoformat(),
                "event": "resolved",
                "key": key,
                "message": known.get("message"),
                "duration_seconds": int(now - float(known.get("since") or now)),
                "channels": outcome,
            },
        )
        counts["cleared"] += 1
    return counts


async def run_alert_checks(_ctx=None) -> dict[str, int]:
    """arq cron (every minute): every company with alerts turned on."""
    from api.db import db_client

    totals = {"organizations": 0, "raised": 0, "cleared": 0}
    for connection in await db_client.list_pbx_connections():
        settings = read_settings(connection)
        if not settings["enabled"] or not (
            settings["webhook_url"] or settings["email_recipients"]
        ):
            continue
        try:
            counts = await check_organization(connection.organization_id)
        except Exception:  # noqa: BLE001 - one company never blocks the others
            logger.opt(exception=True).warning(
                f"Supervision alerts failed for org {connection.organization_id}"
            )
            continue
        totals["organizations"] += 1
        totals["raised"] += counts["raised"]
        totals["cleared"] += counts["cleared"]
    return totals

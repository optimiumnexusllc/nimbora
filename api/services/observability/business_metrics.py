"""Platform-wide business metrics for Prometheus (one scrape for the fleet).

Unlike ``metrics.py`` (per-worker runtime metrics, no I/O), this collector
reads the database and Redis when scraped, so it is served by its own
endpoint (``/api/v1/metrics/business``), scraped once a minute by one job:

* enterprise PBX of each company: reachable, last check, events, alerts open,
  human-minutes catch-up freshness;
* subscriptions by plan and status;
* AI and human minutes of the current calendar month, per company.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from loguru import logger
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily


class _Snapshot:
    """A collector serving families computed beforehand (async) at scrape."""

    def __init__(self, families: list[GaugeMetricFamily]):
        self.families = families

    def collect(self):
        yield from self.families


def _age(moment: datetime | None, now: float) -> float | None:
    return None if moment is None else max(0.0, now - moment.timestamp())


async def _pbx_families(now: float) -> list[GaugeMetricFamily]:
    from api.db import db_client
    from api.services.pbx.alerts import STATE_KEY
    from api.services.supervision.live_calls import get_redis

    up = GaugeMetricFamily(
        "nimbora_pbx_up",
        "1 when the company's PBX answered its last check",
        labels=["organization_id", "managed"],
    )
    checked = GaugeMetricFamily(
        "nimbora_pbx_last_check_age_seconds",
        "Seconds since the PBX connection was last checked",
        labels=["organization_id"],
    )
    events = GaugeMetricFamily(
        "nimbora_pbx_events_connected",
        "1 when the PBX sends its call events to the platform",
        labels=["organization_id"],
    )
    synced = GaugeMetricFamily(
        "nimbora_pbx_usage_sync_age_seconds",
        "Seconds since the human-minutes catch-up last read the PBX call logs",
        labels=["organization_id"],
    )
    alerts = GaugeMetricFamily(
        "nimbora_pbx_alerts_active",
        "Supervision alerts open (long wait, full queue, no agent)",
        labels=["organization_id", "kind"],
    )
    try:
        redis = await get_redis()
    except Exception:  # noqa: BLE001 - PBX state still reported without alerts
        redis = None
    for connection in await db_client.list_pbx_connections():
        org = str(connection.organization_id)
        up.add_metric(
            [org, "true" if connection.managed else "false"],
            1.0 if connection.status == "ok" else 0.0,
        )
        age = _age(connection.last_checked_at, now)
        if age is not None:
            checked.add_metric([org], age)
        events.add_metric([org], 1.0 if connection.webhook_subscription_uuid else 0.0)
        age = _age(connection.usage_synced_at, now)
        if age is not None:
            synced.add_metric([org], age)
        if redis is None:
            continue
        try:
            state = await redis.hgetall(
                STATE_KEY.format(org=connection.organization_id)
            )
        except Exception:  # noqa: BLE001 - alerts of this company skipped
            logger.opt(exception=True).debug("Alert state unreadable")
            continue
        counts: dict[str, int] = {}
        for raw in state.values():
            alert = json.loads(raw)
            if alert.get("active"):
                kind = alert.get("kind") or "unknown"
                counts[kind] = counts.get(kind, 0) + 1
        for kind, count in counts.items():
            alerts.add_metric([org, kind], float(count))
    return [up, checked, events, synced, alerts]


async def _saas_families(now: datetime) -> list[GaugeMetricFamily]:
    from api.db import db_client

    subscriptions = GaugeMetricFamily(
        "nimbora_subscriptions",
        "Companies by plan and subscription status",
        labels=["plan", "status"],
    )
    ai = GaugeMetricFamily(
        "nimbora_ai_minutes_month",
        "AI call minutes of the current calendar month",
        labels=["organization_id"],
    )
    human = GaugeMetricFamily(
        "nimbora_human_minutes_month",
        "Human call minutes (enterprise PBX) of the current calendar month",
        labels=["organization_id"],
    )
    rows, _ = await db_client.list_organization_subscriptions(limit=100000)
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.plan.code, row.status)
        counts[key] = counts.get(key, 0) + 1
    for (plan, status), count in sorted(counts.items()):
        subscriptions.add_metric([plan, status], float(count))
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for organization_id, seconds in sorted(
        (await db_client.get_usage_by_organization(start, now)).items()
    ):
        ai.add_metric([str(organization_id)], round(seconds["ai"] / 60.0, 2))
        human.add_metric([str(organization_id)], round(seconds["human"] / 60.0, 2))
    return [subscriptions, ai, human]


async def render(now: datetime | None = None) -> bytes:
    """Prometheus exposition of the business metrics, computed now."""
    now = now or datetime.now(UTC)
    families: list[GaugeMetricFamily] = []
    for name, builder in (
        ("pbx", lambda: _pbx_families(now.timestamp())),
        ("saas", lambda: _saas_families(now)),
    ):
        try:
            families += await builder()
        except Exception:  # noqa: BLE001 - one source down, the rest is served
            logger.opt(exception=True).warning(f"Business metrics: {name} unavailable")
    scrape = GaugeMetricFamily(
        "nimbora_business_metrics_generated_timestamp_seconds",
        "When these business metrics were computed",
    )
    scrape.add_metric([], time.time())
    families.append(scrape)
    registry = CollectorRegistry()
    registry.register(_Snapshot(families))
    return generate_latest(registry)

"""Fleet-wide business metrics for Prometheus (PBX, subscriptions, minutes)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from prometheus_client.parser import text_string_to_metric_families

from api.routes import main as main_routes
from api.services.observability import business_metrics
from api.services.pbx import service as pbx
from api.services.pbx.alerts import STATE_KEY
from api.services.supervision.live_calls import get_redis


def _samples(text: str) -> dict[tuple[str, tuple], float]:
    out = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            out[(sample.name, tuple(sorted(sample.labels.items())))] = sample.value
    return out


async def _org(db):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    return org


async def test_pbx_alerts_and_minutes_are_exposed(db_session):
    now = datetime.now(UTC)
    org = await _org(db_session)
    await db_session.save_pbx_connection(
        org.id,
        {
            "base_url": "https://pbx.example.com",
            "username": "nimbora",
            "password": "secret",
            "webhook_token": pbx.new_webhook_token(),
            "status": "ok",
            "managed": True,
            "last_checked_at": now - timedelta(seconds=90),
            "usage_synced_at": now - timedelta(minutes=30),
            "webhook_subscription_uuid": "sub-1",
        },
    )
    down = await _org(db_session)
    await db_session.save_pbx_connection(
        down.id,
        {
            "base_url": "https://pbx.down.example",
            "username": "x",
            "password": "y",
            "webhook_token": pbx.new_webhook_token(),
            "status": "error",
        },
    )
    redis = await get_redis()
    key = STATE_KEY.format(org=org.id)
    await redis.hset(
        key, "long_wait:3", json.dumps({"kind": "long_wait", "active": True})
    )
    await redis.hset(
        key, "no_agent:3", json.dumps({"kind": "no_agent", "active": False})
    )
    await db_session.record_human_call_usage(
        org.id,
        {
            "source": "pbx",
            "external_id": uuid.uuid4().hex,
            "direction": "inbound",
            "started_at": now - timedelta(minutes=1),
            "billable_seconds": 150,
        },
    )
    try:
        samples = _samples((await business_metrics.render(now)).decode())
    finally:
        await redis.delete(key)

    o, d = str(org.id), str(down.id)
    assert (
        samples[("nimbora_pbx_up", (("managed", "true"), ("organization_id", o)))] == 1
    )
    assert (
        samples[("nimbora_pbx_up", (("managed", "false"), ("organization_id", d)))] == 0
    )
    age = samples[("nimbora_pbx_last_check_age_seconds", (("organization_id", o),))]
    assert 89 <= age <= 100
    assert samples[("nimbora_pbx_events_connected", (("organization_id", o),))] == 1
    assert samples[("nimbora_pbx_events_connected", (("organization_id", d),))] == 0
    assert (
        samples[
            (
                "nimbora_pbx_alerts_active",
                (("kind", "long_wait"), ("organization_id", o)),
            )
        ]
        == 1
    )
    assert (
        "nimbora_pbx_alerts_active",
        (("kind", "no_agent"), ("organization_id", o)),
    ) not in samples
    assert samples[("nimbora_human_minutes_month", (("organization_id", o),))] == 2.5
    assert ("nimbora_business_metrics_generated_timestamp_seconds", ()) in samples


async def test_one_source_down_still_serves_the_rest(db_session, monkeypatch):
    async def broken(now):
        raise RuntimeError("database down")

    monkeypatch.setattr(business_metrics, "_saas_families", broken)
    text = (await business_metrics.render()).decode()
    assert "nimbora_business_metrics_generated_timestamp_seconds" in text
    assert "nimbora_subscriptions" not in text


def test_business_scrape_is_disabled_by_default_and_guarded(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_api_route("/api/v1/metrics/business", main_routes.business_metrics)
    monkeypatch.setattr("api.constants.ENABLE_PROMETHEUS_METRICS", False)
    with TestClient(app) as client:
        assert client.get("/api/v1/metrics/business").status_code == 404
    monkeypatch.setattr("api.constants.ENABLE_PROMETHEUS_METRICS", True)
    monkeypatch.setattr("api.constants.NIMBORA_DEVOPS_SECRET", "secret")

    async def fake_render():
        return b"# fake\n"

    monkeypatch.setattr(business_metrics, "render", fake_render)
    with TestClient(app) as client:
        assert client.get("/api/v1/metrics/business").status_code == 403
        response = client.get(
            "/api/v1/metrics/business", headers={"X-NIMBORA-Devops-Secret": "secret"}
        )
    assert response.status_code == 200 and response.text == "# fake\n"
    assert response.headers["cache-control"] == "no-store"

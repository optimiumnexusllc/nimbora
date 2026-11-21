"""Human call recordings: recording policy pushed to extensions, import into
the platform's storage, masked transcripts, retention and GDPR."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from api.services.pbx import client as client_module
from api.services.pbx import recordings
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
WAV = b"RIFF" + b"\x00" * 60


class FakeStorage:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def acreate_file_from_bytes(self, key, data):
        self.files[key] = data
        return True

    async def aget_signed_url(self, key, expiration=3600, force_inline=False, **_):
        return (
            f"https://storage.local/{key}?exp={expiration}"
            if key in self.files
            else None
        )

    async def adelete_file(self, key):
        return self.files.pop(key, None) is not None


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield


@pytest.fixture
def storage(monkeypatch):
    fs = FakeStorage()
    monkeypatch.setattr(recordings, "_storage", lambda: (fs, "minio"))
    monkeypatch.setattr(recordings, "_storage_for", lambda backend: fs)
    return fs


def _cdr(cdr_id: int, recording_uuid: str, *, direction="inbound", minutes_ago=30):
    start = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "id": cdr_id,
        "start": start.isoformat(),
        "answered": True,
        "duration": 125.0,
        "call_direction": direction,
        "source_extension": "+2250700112233" if direction == "inbound" else "1001",
        "source_name": "Awa" if direction == "inbound" else "Koffi Yao",
        "destination_extension": "1001" if direction == "inbound" else "+2250700112233",
        "destination_name": "Koffi Yao" if direction == "inbound" else "",
        "recordings": [
            {
                "uuid": recording_uuid,
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(seconds=124)).isoformat(),
                "deleted": False,
                "filename": f"{recording_uuid}.wav",
            }
        ],
    }


async def _setup(db, monkeypatch, fake, policy=None):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
            "recording_policy": policy or {},
        },
    )
    return user, org


def test_card_like_digit_runs_are_masked_even_without_checksum():
    assert (
        recordings.mask_card_like("carte 4970 1012 3456 7890 merci")
        == "carte [CARD] merci"
    )
    assert (
        recordings.mask_card_like("rappel au 07 07 11 22 33")
        == "rappel au 07 07 11 22 33"
    )
    assert recordings.mask_card_like("déjà [CARD] masqué") == "déjà [CARD] masqué"


async def test_policy_switches_recording_on_the_chosen_extensions(
    db_session, monkeypatch
):
    fake = FakePbx()
    _, org = await _setup(db_session, monkeypatch, fake)
    result = await recordings.save_policy(
        org.id,
        recordings.RecordingPolicy(
            incoming_external=True, outgoing_external=True, user_uuids=["u-1"]
        ),
    )
    assert result["extensions_changed"] == 1  # u-2 was already off
    assert fake.user_settings["u-1"] == {
        "call_record_incoming_external_enabled": True,
        "call_record_outgoing_external_enabled": True,
        "call_record_incoming_internal_enabled": False,
        "call_record_outgoing_internal_enabled": False,
    }
    assert fake.user_settings.get("u-2", {}) == {}
    # Every extension, internal calls too.
    result = await recordings.save_policy(
        org.id, recordings.RecordingPolicy(incoming_external=True, internal=True)
    )
    assert result["extensions_changed"] == 2
    assert fake.user_settings["u-2"]["call_record_outgoing_internal_enabled"] is True
    assert fake.user_settings["u-1"]["call_record_outgoing_external_enabled"] is False
    # Nothing to change: no call to the PBX.
    assert (
        await recordings.save_policy(
            org.id, recordings.RecordingPolicy(incoming_external=True, internal=True)
        )
    )["extensions_changed"] == 0
    connection = await db_session.get_pbx_connection(org.id)
    assert recordings.policy_of(connection).internal is True
    with pytest.raises(pbx.PbxRouteError):
        await recordings.save_policy(
            org.id, recordings.RecordingPolicy(user_uuids=["u-404"])
        )


async def test_import_transcribe_mask_and_remove_from_pbx(
    db_session, monkeypatch, storage
):
    fake = FakePbx()
    _, org = await _setup(
        db_session,
        monkeypatch,
        fake,
        policy={"import_enabled": True, "transcribe": True, "remove_from_pbx": True},
    )
    fake.recording_media["rec-1"] = WAV
    cdr = _cdr(901, "rec-1")

    async def fake_transcribe(audio, mime, stt, transport=None):
        assert audio == WAV and mime == "audio/wav"
        return "Ma carte est 4111 1111 1111 1111, cryptogramme 123, merci Koffi."

    from api.services.configuration import model_connections
    from api.services.whatsapp_messaging import transcribe

    async def fake_resolve(organization_id, *args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(effective=SimpleNamespace(stt="stt"))

    monkeypatch.setattr(transcribe, "transcribe_voice_note", fake_transcribe)
    monkeypatch.setattr(model_connections, "resolve_model_configuration", fake_resolve)

    connection = await db_session.get_pbx_connection(org.id)
    assert await recordings.import_cdr(connection, cdr) == 1
    assert await recordings.import_cdr(connection, cdr) == 0  # idempotent
    rows, total = await db_session.list_pbx_recordings(org.id)
    row = rows[0]
    assert total == 1 and row.removed_from_pbx and fake.deleted_media == ["rec-1"]
    assert row.duration_seconds == 124 and row.customer_phone == "+2250700112233"
    assert row.direction == "inbound" and row.destination_name == "Koffi Yao"
    assert "4111" not in row.transcript and "[CARD]" in row.transcript
    assert "[CVV]" in row.transcript and row.transcript_status == "done"
    assert storage.files[row.storage_key] == WAV
    assert row.storage_key.startswith(f"pbx-recordings/{org.id}/")

    url = await recordings.audio_url(org.id, row.id)
    assert url.startswith("https://storage.local/") and "exp=900" in url
    _, other = await _setup(db_session, monkeypatch, FakePbx())
    with pytest.raises(pbx.PbxRouteError):
        await recordings.audio_url(other.id, row.id)  # another organization

    # Search, GDPR export and erasure.
    found, _ = await db_session.list_pbx_recordings(org.id, search="Koffi")
    assert [r.id for r in found] == [row.id]
    from api.services.privacy.service import erase_subject, export_subject

    export = await export_subject(org.id, "+225 07 00 11 22 33")
    assert export["summary"]["human_call_recordings"] == 1
    assert export["human_call_recordings"][0]["with"] == "Koffi Yao"
    request = await erase_subject(org.id, "+2250700112233")
    assert request.counts["human_call_recordings"] == 1
    assert storage.files == {}


async def test_sync_catches_up_and_skips_ai_and_disabled(
    db_session, monkeypatch, storage
):
    fake = FakePbx()
    _, org = await _setup(
        db_session, monkeypatch, fake, policy={"import_enabled": True}
    )
    fake.cdr = [_cdr(910, "rec-a"), _cdr(911, "rec-b", direction="outbound")]
    fake.recording_media.update({"rec-a": WAV, "rec-b": WAV})
    result = await recordings.sync_recordings(org.id)
    assert result == {"imported": 2, "seen": 2}
    assert fake.deleted_media == []  # kept on the PBX by default
    assert (await recordings.sync_recordings(org.id))["imported"] == 0
    connection = await db_session.get_pbx_connection(org.id)
    assert connection.recordings_synced_at is not None
    rows, _ = await db_session.list_pbx_recordings(org.id)
    assert {r.transcript_status for r in rows} == {"none"}

    # Retention purges old recordings (files and rows).
    from api.services.privacy.service import PrivacySettings, apply_retention

    old = rows[0]
    await db_session.update_pbx_recording(
        org.id, old.id, {"started_at": datetime.now(UTC) - timedelta(days=40)}
    )
    counts = await apply_retention(org.id, PrivacySettings(recording_retention_days=30))
    assert counts["human_call_recordings"] == 1
    assert len(storage.files) == 1

    # Import switched off: nothing is fetched.
    await db_session.save_pbx_connection(
        org.id, {"recording_policy": {"import_enabled": False}}
    )
    fake.cdr = [_cdr(912, "rec-c")]
    fake.recording_media["rec-c"] = WAV
    assert await recordings.sync_recordings(org.id) == {"imported": 0, "seen": 0}


async def test_webhook_queues_the_import(db_session, monkeypatch, storage):
    fake = FakePbx()
    _, org = await _setup(
        db_session, monkeypatch, fake, policy={"import_enabled": True}
    )
    queued = []

    async def fake_enqueue(name, *args, **kwargs):
        queued.append((name, args))

    monkeypatch.setattr("api.tasks.arq.enqueue_job", fake_enqueue)
    connection = await db_session.get_pbx_connection(org.id)
    cdr = _cdr(920, "rec-w")
    await pbx.handle_event(connection, "call_log_created", {"data": cdr})
    assert queued == [("import_pbx_recordings", (org.id, cdr))]

    # The queued job imports it.
    fake.recording_media["rec-w"] = WAV
    assert await recordings.import_pbx_recordings({}, org.id, cdr) == 1


async def test_routes(db_session, monkeypatch, storage, test_client_factory):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    fake.cdr = [_cdr(930, "rec-r")]
    fake.recording_media["rec-r"] = WAV
    async with test_client_factory(user) as client:
        saved = await client.put(
            "/api/v1/pbx/recordings/policy",
            json={"incoming_external": True, "import_enabled": True},
        )
        assert saved.status_code == 200 and saved.json()["extensions_changed"] == 2
        assert (await client.post("/api/v1/pbx/recordings/sync")).json()[
            "imported"
        ] == 1
        listed = (await client.get("/api/v1/pbx/recordings")).json()
        assert listed["total"] == 1 and listed["policy"]["incoming_external"] is True
        item = listed["items"][0]
        assert item["source_name"] == "Awa" and item["duration_seconds"] == 124
        audio = (await client.get(f"/api/v1/pbx/recordings/{item['id']}/audio")).json()
        assert audio["url"].startswith("https://storage.local/")
        assert (
            await client.delete(f"/api/v1/pbx/recordings/{item['id']}")
        ).status_code == 204
        assert (
            await client.delete(f"/api/v1/pbx/recordings/{item['id']}")
        ).status_code == 404

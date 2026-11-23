"""Bundled object store: SeaweedFS by default (S3 backend), never an empty
store for an install that already has files elsewhere."""

import uuid

import pytest

from api.constants import _object_store_settings


def test_new_installs_use_the_bundled_seaweedfs_through_s3():
    s = _object_store_settings(
        {
            "OBJECT_STORE": "seaweedfs",
            "MINIO_ACCESS_KEY": "nimbora1",
            "MINIO_SECRET_KEY": "secret",
            "PUBLIC_BASE_URL": "https://app.example.com",
        }
    )
    assert s["store"] == "seaweedfs" and s["bundled_seaweedfs"] and s["enable_aws_s3"]
    assert (s["s3_endpoint_url"], s["s3_bucket"]) == (
        "http://seaweedfs:8333",
        "voice-audio",
    )
    assert (s["s3_signature_version"], s["s3_addressing_style"]) == ("s3v4", "path")
    # Browsers go through the proxy's /voice-audio/ path, with signed links.
    assert s["s3_public_endpoint_url"] == "https://app.example.com"
    assert (s["s3_access_key"], s["s3_secret_key"]) == ("nimbora1", "secret")


@pytest.mark.parametrize(
    "env",
    [
        # Moved to AWS S3 (no custom endpoint), then updated: the new compose
        # default OBJECT_STORE=seaweedfs must not send it to an empty store.
        {"OBJECT_STORE": "seaweedfs", "ENABLE_AWS_S3": "true", "S3_BUCKET": "mine"},
        {
            "OBJECT_STORE": "seaweedfs",
            "ENABLE_AWS_S3": "true",
            "S3_BUCKET": "mine",
            "S3_ENDPOINT_URL": "https://s3.fr-par.scw.cloud",
        },
    ],
)
def test_an_install_on_an_external_s3_service_stays_on_it(env):
    s = _object_store_settings(env)
    assert s["store"] == "s3" and not s["bundled_seaweedfs"]
    assert s["s3_bucket"] == "mine"
    assert s["s3_endpoint_url"] == env.get("S3_ENDPOINT_URL")
    assert s["s3_public_endpoint_url"] is None


def test_without_a_setting_local_development_keeps_minio():
    assert _object_store_settings({})["store"] == "minio"
    assert _object_store_settings({"OBJECT_STORE": "minio"})["enable_aws_s3"] is False
    assert _object_store_settings({"OBJECT_STORE": "nonsense"})["store"] == "minio"


@pytest.fixture(scope="module")
def s3_server():
    ThreadedMotoServer = pytest.importorskip("moto.server").ThreadedMotoServer
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


def _store(url, bucket):
    from api.services.filesystem.s3 import S3FileSystem

    return S3FileSystem(
        bucket_name=bucket,
        endpoint_url=url,
        signature_version="s3v4",
        addressing_style="path",
        public_endpoint_url="https://app.example.com",
        access_key="nimbora1",
        secret_key="secret",
    )


async def test_the_bucket_is_created_once_with_the_store_keys(s3_server, monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)  # explicit keys, not the environment
    fs = _store(s3_server, f"voice-audio-{uuid.uuid4().hex[:8]}")
    assert await fs.aensure_bucket() is True
    assert await fs.aensure_bucket() is False  # already there
    import io

    class Body(io.BytesIO):
        async def read(self, n=-1):
            return super().read(n)

    assert await fs.acreate_file("calls/1.wav", Body(b"RIFF"))
    url = await fs.aget_signed_url("calls/1.wav")
    # Signed for the public address, path-style, under the bucket's path.
    assert url.startswith(f"https://app.example.com/{fs.bucket_name}/calls/1.wav?")
    assert "X-Amz-Signature=" in url


async def test_startup_creates_the_bucket_and_reports_files_left_on_minio(
    db_session, s3_server, monkeypatch
):
    from api import constants
    from api.services import storage

    fs = _store(s3_server, f"voice-audio-{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(constants, "BUNDLED_SEAWEEDFS", True)
    monkeypatch.setattr(constants, "OBJECT_STORE", "seaweedfs")
    monkeypatch.setattr(storage, "storage_fs", fs)

    async def counts(backend):
        assert backend == "minio"
        return 12

    from api.db import db_client

    monkeypatch.setattr(db_client, "count_storage_backend", counts)
    await storage.startup_checks(attempts=1)
    assert await fs.aensure_bucket() is False  # created at start-up
    assert storage.LEGACY_MINIO_FILES == 12

    # On MinIO itself nothing is reported.
    monkeypatch.setattr(constants, "OBJECT_STORE", "minio")
    monkeypatch.setattr(constants, "BUNDLED_SEAWEEDFS", False)
    monkeypatch.setattr(storage, "LEGACY_MINIO_FILES", 0)
    await storage.startup_checks(attempts=1)
    assert storage.LEGACY_MINIO_FILES == 0


async def test_health_says_which_store_is_in_use(monkeypatch, test_client_factory):
    from api import constants
    from api.services import storage

    monkeypatch.setattr(constants, "BUNDLED_SEAWEEDFS", True)
    monkeypatch.setattr(storage, "LEGACY_MINIO_FILES", 3)
    async with test_client_factory(None) as client:
        body = (await client.get("/api/v1/health")).json()
    assert (body["object_store"], body["legacy_minio_files"]) == ("seaweedfs", 3)


async def test_files_still_on_minio_are_counted(db_session):
    from datetime import UTC, datetime

    user = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:8]}@x.io", password_hash="x"
    )
    org, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"o{uuid.uuid4().hex}", user_id=user.id
    )
    before = await db_session.count_storage_backend("minio")
    await db_session.create_pbx_recording(
        org.id,
        {
            "cdr_id": 1,
            "recording_uuid": uuid.uuid4().hex,
            "started_at": datetime.now(UTC),
            "storage_backend": "minio",
            "storage_key": "k",
        },
    )
    assert await db_session.count_storage_backend("minio") == before + 1

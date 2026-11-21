"""Leaving the bundled MinIO: copy, verify, switch; S3 links for browsers."""

import uuid
from urllib.parse import urlparse

import boto3
import httpx
import pytest
from minio import Minio

from api.services.filesystem import migration
from api.services.filesystem.s3 import S3FileSystem


@pytest.fixture(scope="module")
def s3_server():
    # An S3 server in the test process (dev dependency moto[server]).
    ThreadedMotoServer = pytest.importorskip("moto.server").ThreadedMotoServer
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"{host}:{port}"
    server.stop()


@pytest.fixture
def stores(s3_server, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    suffix = uuid.uuid4().hex[:8]
    source, destination = f"voice-audio-{suffix}", f"durable-{suffix}"
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{s3_server}",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    s3.create_bucket(Bucket=source)
    s3.create_bucket(Bucket=destination)
    for key, body in {
        "recordings/2026/11/a.wav": b"RIFF" * 300,
        "transcripts/a.txt": b"Bonjour",
        "kb/doc.pdf": b"%PDF-1.7",
    }.items():
        s3.put_object(
            Bucket=source, Key=key, Body=body, ContentType="application/x-test"
        )
    minio = Minio(
        s3_server,
        access_key="test",
        secret_key="test",
        secure=False,
        region="us-east-1",
    )
    return minio, source, s3, destination


def test_copy_is_resumable_and_verify_finds_everything(stores):
    minio, source, s3, destination = stores

    dry = migration.copy_objects(minio, source, s3, destination, dry_run=True)
    assert (dry.objects, dry.copied) == (3, 3)
    assert migration.verify_objects(minio, source, s3, destination).missing

    s3.put_object(
        Bucket=destination, Key="kb/doc.pdf", Body=b"%PDF-1.7"
    )  # already there
    first = migration.copy_objects(minio, source, s3, destination)
    assert (first.copied, first.skipped) == (2, 1)
    copied = s3.get_object(Bucket=destination, Key="recordings/2026/11/a.wav")
    assert copied["Body"].read() == b"RIFF" * 300
    assert copied["ContentType"] == "application/x-test"

    # A file added since: the last run before switching copies only it.
    s3.put_object(Bucket=source, Key="recordings/new.wav", Body=b"new")
    again = migration.copy_objects(minio, source, s3, destination)
    assert (again.copied, again.skipped) == (1, 3)
    report = migration.verify_objects(minio, source, s3, destination)
    assert report.complete and report.objects == 4


def test_verify_reports_a_different_size(stores):
    minio, source, s3, destination = stores
    migration.copy_objects(minio, source, s3, destination)
    s3.put_object(Bucket=destination, Key="transcripts/a.txt", Body=b"coupe")
    report = migration.verify_objects(minio, source, s3, destination)
    assert report.mismatched == ["transcripts/a.txt"] and not report.complete


async def test_switch_points_stored_files_to_s3(db_session):
    from api.db.models import PbxCallRecordingModel

    user = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    async with db_session.async_session() as session:
        row = PbxCallRecordingModel(
            organization_id=org.id,
            cdr_id=1,
            recording_uuid=uuid.uuid4().hex,
            storage_backend="minio",
            storage_key="pbx/1.wav",
        )
        session.add(row)
        await session.commit()
        row_id = row.id
    changed = await migration.switch_database()
    assert changed["pbx_call_recordings"] >= 1
    async with db_session.async_session() as session:
        assert (
            await session.get(PbxCallRecordingModel, row_id)
        ).storage_backend == "s3"


async def test_s3_links_use_the_public_address_and_work(stores, s3_server):
    _, source, _, _ = stores
    fs = S3FileSystem(
        bucket_name=source,
        endpoint_url="http://object-store.internal:8333",
        addressing_style="path",
        signature_version="s3v4",
        public_endpoint_url=f"http://{s3_server}",
    )
    url = await fs.aget_signed_url("transcripts/a.txt", force_inline=True)
    parsed = urlparse(url)
    assert parsed.netloc == s3_server and parsed.path == f"/{source}/transcripts/a.txt"
    assert "X-Amz-Signature" in parsed.query
    async with httpx.AsyncClient() as client:
        assert (await client.get(url)).content == b"Bonjour"

    internal = await fs.aget_signed_url("transcripts/a.txt", use_internal_endpoint=True)
    assert urlparse(internal).netloc == "object-store.internal:8333"
    upload = await fs.aget_presigned_put_url("kb/new.pdf")
    assert urlparse(upload).netloc == s3_server


async def test_without_public_address_links_keep_the_endpoint():
    fs = S3FileSystem(
        bucket_name="b",
        endpoint_url="https://s3.fr-par.scw.cloud",
        addressing_style="path",
    )
    url = await fs.aget_signed_url("a.wav")
    assert urlparse(url).netloc == "s3.fr-par.scw.cloud"

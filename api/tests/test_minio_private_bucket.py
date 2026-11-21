"""Bundled object storage: private bucket, every link signed and expiring.

Earlier versions set an anonymous read/write/list policy on the bucket and
returned plain URLs, so anyone reaching the public /voice-audio/ path could
list, download or overwrite call recordings.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from minio import Minio
from minio.error import S3Error

from api.services.filesystem.minio import MinioFileSystem


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        Minio, "bucket_exists", lambda self, b: seen.append(("exists", b)) or True
    )
    monkeypatch.setattr(Minio, "make_bucket", lambda self, b: seen.append(("make", b)))
    monkeypatch.setattr(
        Minio, "set_bucket_policy", lambda self, b, p: seen.append(("set_policy", b, p))
    )
    monkeypatch.setattr(
        Minio, "delete_bucket_policy", lambda self, b: seen.append(("delete_policy", b))
    )
    return seen


def _fs(**kwargs):
    return MinioFileSystem(
        endpoint="minio:9000",
        access_key="AKIA",
        secret_key="secret",
        bucket_name="voice-audio",
        public_endpoint=kwargs.pop("public_endpoint", "https://app.example.com"),
        **kwargs,
    )


def test_bucket_is_made_private_at_start(calls):
    _fs()
    assert ("delete_policy", "voice-audio") in calls
    assert not any(c[0] == "set_policy" for c in calls)  # never opened again


def test_no_policy_to_remove_is_fine(calls, monkeypatch):
    def none(self, bucket):
        raise S3Error("NoSuchBucketPolicy", "none", "/", "r", "h", None)

    monkeypatch.setattr(Minio, "delete_bucket_policy", none)
    assert _fs().ensure_private() is True


async def test_download_links_are_signed_for_the_public_host(calls):
    url = await _fs().aget_signed_url(
        "recordings/42.wav", expiration=600, force_inline=True
    )
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "app.example.com",
        "/voice-audio/recordings/42.wav",
    )
    query = parse_qs(parsed.query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["600"]
    assert query["X-Amz-Signature"][0]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert query["response-content-disposition"] == ["inline"]


async def test_server_side_links_are_signed_for_the_internal_host(calls):
    url = await _fs().aget_signed_url("campaigns/list.csv", use_internal_endpoint=True)
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc) == ("http", "minio:9000")
    assert "X-Amz-Signature" in parsed.query


async def test_upload_links_are_signed_puts_that_expire(calls):
    url = await _fs(public_endpoint="http://localhost:9000").aget_presigned_put_url(
        "kb/doc.pdf", expiration=900
    )
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "http",
        "localhost:9000",
        "/voice-audio/kb/doc.pdf",
    )
    query = parse_qs(parsed.query)
    assert query["X-Amz-Expires"] == ["900"] and query["X-Amz-Signature"][0]


def test_public_endpoint_must_be_a_host(calls):
    with pytest.raises(ValueError, match="scheme and host only"):
        _fs(public_endpoint="https://app.example.com/storage")
    with pytest.raises(ValueError, match="scheme"):
        _fs(public_endpoint="app.example.com")


def test_inline_links_carry_the_media_type(monkeypatch):
    """Through Traefik a .wav came back as application/octet-stream: the signed
    link must ask for the real media type when it is meant to play inline."""
    from urllib.parse import parse_qs, urlparse

    import asyncio

    from api.services.filesystem.minio import MinioFileSystem

    fs = MinioFileSystem.__new__(MinioFileSystem)
    captured = {}

    class _Client:
        def presigned_get_object(self, bucket, key, expires, response_headers=None):
            captured.update(response_headers or {})
            return "https://example.com/" + key + "?signed"

    fs.bucket_name = "voice-audio"
    fs.client = fs.public_client = _Client()
    asyncio.run(fs.aget_signed_url("recordings/42.wav", force_inline=True))
    assert captured == {"response-content-disposition": "inline", "response-content-type": "audio/wav"}
    captured.clear()
    asyncio.run(fs.aget_signed_url("kb/doc.pdf", force_inline=True))
    assert captured == {"response-content-disposition": "inline"}

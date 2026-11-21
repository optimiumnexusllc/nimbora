"""Move every object from the bundled MinIO to another S3-compatible store.

For operators leaving the bundled MinIO (its last open-source image no longer
gets security updates) for a maintained S3 service (Scaleway, OVHcloud,
Cloudflare R2, Wasabi, AWS) or a self-hosted one (SeaweedFS, Garage).

1. ``copy``: every object of the source bucket is copied to the destination
   bucket, skipping those already there with the same size: interrupted runs
   resume, and a last run just before switching copies what was added since.
2. ``verify``: every source object exists at the destination with its size.
3. ``switch``: database rows pointing at MinIO now point at the S3 backend;
   then set ENABLE_AWS_S3=true (and the S3_* settings) and restart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class MigrationReport:
    objects: int = 0
    bytes: int = 0
    copied: int = 0
    skipped: int = 0
    missing: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.mismatched


def _source_objects(minio_client, bucket: str):
    for item in minio_client.list_objects(bucket, recursive=True):
        if not item.is_dir:
            yield item.object_name, int(item.size or 0)


def _destination_size(s3_client, bucket: str, key: str) -> int | None:
    from botocore.exceptions import ClientError

    try:
        return int(s3_client.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return None
        raise


def copy_objects(
    minio_client,
    source_bucket: str,
    s3_client,
    destination_bucket: str,
    *,
    dry_run: bool = False,
    progress: Callable[[str], Any] | None = None,
) -> MigrationReport:
    """Copy what is missing at the destination (idempotent, resumable)."""
    report = MigrationReport()
    for key, size in _source_objects(minio_client, source_bucket):
        report.objects += 1
        report.bytes += size
        if _destination_size(s3_client, destination_bucket, key) == size:
            report.skipped += 1
            continue
        if not dry_run:
            response = minio_client.get_object(source_bucket, key)
            try:
                content_type = (
                    response.headers.get("Content-Type") or "application/octet-stream"
                )
                s3_client.upload_fileobj(
                    response,
                    destination_bucket,
                    key,
                    ExtraArgs={"ContentType": content_type},
                )
            finally:
                response.close()
                response.release_conn()
        report.copied += 1
        if progress and report.copied % 100 == 0:
            progress(f"{report.copied} objects copied")
    return report


def verify_objects(
    minio_client, source_bucket: str, s3_client, destination_bucket: str
) -> MigrationReport:
    """Every source object at the destination, with the same size."""
    report = MigrationReport()
    for key, size in _source_objects(minio_client, source_bucket):
        report.objects += 1
        report.bytes += size
        found = _destination_size(s3_client, destination_bucket, key)
        if found is None:
            report.missing.append(key)
        elif found != size:
            report.mismatched.append(key)
    return report


async def switch_database(old: str = "minio", new: str = "s3") -> dict[str, int]:
    from api.db import db_client

    changed = await db_client.reassign_storage_backend(old, new)
    logger.info(f"Storage backend switched from {old} to {new}: {changed}")
    return changed


def clients_from_settings():
    """(MinIO client, its bucket, S3 client, its bucket) from the API settings."""
    import boto3
    from api import constants
    from botocore.config import Config
    from minio import Minio

    if not constants.S3_BUCKET:
        raise SystemExit(
            "S3_BUCKET (et S3_ENDPOINT_URL hors AWS) requis pour la destination"
        )
    minio_client = Minio(
        constants.MINIO_ENDPOINT,
        access_key=constants.MINIO_ACCESS_KEY,
        secret_key=constants.MINIO_SECRET_KEY,
        secure=constants.MINIO_SECURE,
    )
    config: dict[str, Any] = {}
    if constants.S3_SIGNATURE_VERSION:
        config["signature_version"] = constants.S3_SIGNATURE_VERSION
    if constants.S3_ADDRESSING_STYLE:
        config["s3"] = {"addressing_style": constants.S3_ADDRESSING_STYLE}
    s3_client = boto3.client(
        "s3",
        region_name=constants.S3_REGION,
        endpoint_url=constants.S3_ENDPOINT_URL,
        config=Config(**config) if config else None,
    )
    return minio_client, constants.MINIO_BUCKET, s3_client, constants.S3_BUCKET


async def run(
    action: str, *, dry_run: bool = False
) -> MigrationReport | dict[str, int]:
    if action == "switch":
        return await switch_database()
    minio_client, source, s3_client, destination = clients_from_settings()
    if action == "copy":
        return await asyncio.to_thread(
            copy_objects,
            minio_client,
            source,
            s3_client,
            destination,
            dry_run=dry_run,
            progress=logger.info,
        )
    if action == "verify":
        return await asyncio.to_thread(
            verify_objects, minio_client, source, s3_client, destination
        )
    raise ValueError(f"Unknown action: {action}")

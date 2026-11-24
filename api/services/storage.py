from loguru import logger

from api.constants import (
    ENABLE_AWS_S3,
    ENVIRONMENT,
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_PUBLIC_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    S3_ACCESS_KEY,
    S3_ADDRESSING_STYLE,
    S3_BUCKET,
    S3_ENDPOINT_URL,
    S3_PUBLIC_ENDPOINT_URL,
    S3_REGION,
    S3_SECRET_KEY,
    S3_SIGNATURE_VERSION,
)
from api.enums import Environment, StorageBackend

from .filesystem import BaseFileSystem, MinioFileSystem, NullFileSystem, S3FileSystem


def get_storage_for_backend(backend: str) -> BaseFileSystem:
    """Get storage instance for a specific backend enum.

    Maps StorageBackend enum codes to actual storage implementations:
    - Code 1 (S3): AWS S3 via S3FileSystem
    - Code 2 (MINIO): MinIO via MinioFileSystem
    """
    # Code 2: MinIO implementation (local/OSS deployments)
    if backend == StorageBackend.MINIO.value:
        if not MINIO_PUBLIC_ENDPOINT:
            raise ValueError(
                "MINIO_PUBLIC_ENDPOINT is required for MinIO storage. "
                "Set it to the full URL browsers use to reach MinIO, "
                "e.g. 'http://localhost:9000' for local dev or "
                "'https://your-server.example.com' for a remote deployment."
            )
        if (
            ENVIRONMENT != Environment.LOCAL.value
            and "localhost" in MINIO_PUBLIC_ENDPOINT
        ):
            logger.warning(
                "MINIO_PUBLIC_ENDPOINT is {} outside local development: signed "
                "download and upload links will not work for remote browsers. Set "
                "it (or PUBLIC_BASE_URL) to the public address.",
                MINIO_PUBLIC_ENDPOINT,
            )
        logger.info(
            f"Initializing {backend} storage at {MINIO_ENDPOINT} "
            f"(public: {MINIO_PUBLIC_ENDPOINT}) with bucket '{MINIO_BUCKET}'"
        )
        return MinioFileSystem(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            bucket_name=MINIO_BUCKET,
            secure=MINIO_SECURE,
            public_endpoint=MINIO_PUBLIC_ENDPOINT,
        )

    # Code 1: AWS S3 implementation (cloud deployments)
    elif backend == StorageBackend.S3.value:
        if not S3_BUCKET:
            raise ValueError(
                "S3_BUCKET environment variable is required when using S3 storage"
            )
        bucket = S3_BUCKET
        region = S3_REGION
        logger.info(
            f"Initializing {backend} storage with bucket '{bucket}' in region '{region}'"
        )
        return S3FileSystem(
            bucket_name=bucket,
            region_name=region,
            endpoint_url=S3_ENDPOINT_URL,
            signature_version=S3_SIGNATURE_VERSION,
            addressing_style=S3_ADDRESSING_STYLE,
            public_endpoint_url=S3_PUBLIC_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
        )

    # Future backend implementations can be added here:
    # elif backend == StorageBackend.GCS:  # Code 3
    #     return GoogleCloudFileSystem(...)
    # elif backend == StorageBackend.AZURE:  # Code 4
    #     return AzureBlobFileSystem(...)

    else:
        raise ValueError(f"Unknown storage backend: {backend}")


def get_current_storage_backend() -> StorageBackend:
    """Get the current storage backend enum."""
    return StorageBackend.get_current_backend()


# Create a single storage instance at module load time.
# In the test environment we skip the real backend so import doesn't require
# MinIO/S3 to be reachable; tests that need storage must inject a real fs.
if ENVIRONMENT == Environment.TEST.value:
    logger.info("ENVIRONMENT=test — using NullFileSystem (no storage backend)")
    storage_fs: BaseFileSystem = NullFileSystem()
else:
    _backend = StorageBackend.get_current_backend()
    logger.info(
        f"Initializing storage backend: {_backend.name} (value: {_backend.value}, ENABLE_AWS_S3={ENABLE_AWS_S3})"
    )
    storage_fs = get_storage_for_backend(_backend.value)


# For backward compatibility, keep get_storage() function
def get_storage() -> BaseFileSystem:
    """Get the module-level storage instance.

    Deprecated: Use 'from api.services.storage import storage_fs' instead.
    """
    return storage_fs


# Files still on the bundled MinIO while the API is set to another store:
# reported by /api/v1/health so an upgrade that left MinIO behind shows.
LEGACY_MINIO_FILES = 0


async def startup_checks(attempts: int = 10, delay: float = 3.0) -> None:
    """Bundled SeaweedFS: create the bucket on first start. Any store but MinIO:
    warn about files still on MinIO (an update that switched the default store
    before the files were migrated). Never stops the API."""
    import asyncio

    global LEGACY_MINIO_FILES
    from api import constants

    if constants.BUNDLED_SEAWEEDFS and isinstance(storage_fs, S3FileSystem):
        for attempt in range(1, attempts + 1):
            try:
                if await storage_fs.aensure_bucket():
                    logger.info(
                        f"Object store: bucket '{storage_fs.bucket_name}' created on SeaweedFS"
                    )
                break
            except Exception as error:  # noqa: BLE001 - SeaweedFS may still be starting
                if attempt == attempts:
                    logger.error(f"Object store: SeaweedFS unreachable ({error})")
                else:
                    await asyncio.sleep(delay)
    if constants.OBJECT_STORE != "minio":
        try:
            from api.db import db_client

            LEGACY_MINIO_FILES = await db_client.count_storage_backend(
                StorageBackend.MINIO.value
            )
        except Exception:  # noqa: BLE001 - informative only
            logger.opt(exception=True).debug("Legacy MinIO file count unavailable")
        if LEGACY_MINIO_FILES:
            logger.error(
                f"Object store is {constants.OBJECT_STORE} but {LEGACY_MINIO_FILES} "
                "files are still on the bundled MinIO: keep it running "
                "(COMPOSE_PROFILES=minio) and migrate them "
                "(python -m scripts.migrate_object_store copy / verify / switch), "
                "or set OBJECT_STORE=minio. See docs/deployment/object-storage.mdx."
            )

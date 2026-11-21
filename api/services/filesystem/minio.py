import asyncio
import io
from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from loguru import logger
from minio import Minio
from minio.error import S3Error

from .base import AsyncReadable, BaseFileSystem


class MinioFileSystem(BaseFileSystem):
    """MinIO implementation of the filesystem interface for OSS users.

    Two endpoints, two different purposes:
    - endpoint (host:port) + secure (bool): used by the MinIO SDK for
      container-to-container calls. The SDK requires these split.
    - public_endpoint (full URL, e.g. "https://example.com"): the address
      browsers use. Download and upload links are signed for that host (the
      reverse proxy must keep the Host header and the /<bucket>/ path, which
      nginx, Caddy and Traefik do). Required.

    The bucket is private: every link is a signed URL that expires. Earlier
    versions made the bucket readable, writable and listable by anyone (to
    dodge signature mismatches between the internal and public hosts), which
    exposed recordings to whoever reached the public /voice-audio/ path; the
    anonymous policy is removed at start-up.
    """

    def __init__(
        self,
        endpoint: str = "localhost:9000",
        access_key: str = "minioadmin",
        secret_key: str = "minioadmin",
        bucket_name: str = "voice-audio",
        secure: bool = False,
        public_endpoint: Optional[str] = None,
        region: str = "us-east-1",
    ):
        if not public_endpoint:
            raise ValueError(
                "MinioFileSystem requires public_endpoint (set MINIO_PUBLIC_ENDPOINT). "
                "Expected a full URL with scheme, e.g. 'http://localhost:9000' or 'https://example.com'."
            )
        if not (
            public_endpoint.startswith("http://")
            or public_endpoint.startswith("https://")
        ):
            raise ValueError(
                f"MINIO_PUBLIC_ENDPOINT must include a scheme (http:// or https://), got: {public_endpoint!r}"
            )

        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.public_endpoint = public_endpoint.rstrip("/")
        self.secure = secure
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region

        public = urlparse(self.public_endpoint)
        if public.path not in {"", "/"}:
            raise ValueError(
                "MINIO_PUBLIC_ENDPOINT must be a scheme and host only (e.g. "
                f"'https://app.example.com'), got: {public_endpoint!r}"
            )

        # Client for internal operations (uploads, etc.)
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        # Signs the links browsers follow, for the host they will send. With
        # the region given, presigning is computed locally (no request).
        self.public_client = Minio(
            public.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=public.scheme == "https",
            region=region,
        )

        # Ensure the bucket exists, and is private.
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except Exception as e:
            logger.debug(f"Bucket setup note: {e}")
        self.ensure_private()

    def ensure_private(self) -> bool:
        """Remove any anonymous access policy from the bucket."""
        try:
            self.client.delete_bucket_policy(self.bucket_name)
            return True
        except S3Error as error:
            if getattr(error, "code", "") == "NoSuchBucketPolicy":
                return True
            logger.warning(f"Could not make bucket {self.bucket_name} private: {error}")
        except Exception as error:  # noqa: BLE001 - storage may start later
            logger.debug(f"Bucket privacy not checked yet: {error}")
        return False

    async def acreate_file(self, file_path: str, content: AsyncReadable) -> bool:
        try:
            data = await content.read()

            def _put():
                # The MinIO SDK requires a stream with .read(), not raw bytes.
                self.client.put_object(
                    self.bucket_name,
                    file_path,
                    data=io.BytesIO(data),
                    length=len(data),
                )

            await asyncio.to_thread(_put)
            return True
        except S3Error:
            return False

    async def aupload_file(self, local_path: str, destination_path: str) -> bool:
        try:

            def _fput():
                self.client.fput_object(self.bucket_name, destination_path, local_path)

            await asyncio.to_thread(_fput)
            return True
        except S3Error:
            return False

    async def aget_signed_url(
        self,
        file_path: str,
        expiration: int = 3600,
        force_inline: bool = False,
        use_internal_endpoint: bool = False,
    ) -> Optional[str]:
        """A download link that expires (signed for the host that will use it)."""
        try:
            client = self.client if use_internal_endpoint else self.public_client
            extra = {"response-content-disposition": "inline"} if force_inline else None
            return client.presigned_get_object(
                self.bucket_name,
                file_path,
                expires=timedelta(seconds=max(1, int(expiration))),
                response_headers=extra,
            )
        except Exception as e:
            logger.error(f"Error generating MinIO URL: {e}")
            return None

    async def aget_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get MinIO object metadata."""
        try:

            def _stat():
                return self.client.stat_object(self.bucket_name, file_path)

            stat = await asyncio.to_thread(_stat)
            return {
                "size": stat.size,
                "created_at": stat.last_modified,
                "modified_at": stat.last_modified,
                "etag": stat.etag.strip('"') if stat.etag else None,
                "content_type": stat.content_type,
                "storage_class": None,  # MinIO doesn't have storage classes like S3
            }
        except S3Error:
            return None

    async def aget_presigned_put_url(
        self,
        file_path: str,
        expiration: int = 900,
        content_type: str = "text/csv",
        max_size: int = 10_485_760,
    ) -> Optional[str]:
        """An upload link (PUT) that expires, signed for the public host."""
        try:
            return self.public_client.presigned_put_object(
                self.bucket_name,
                file_path,
                expires=timedelta(seconds=max(1, int(expiration))),
            )
        except Exception as e:
            logger.error(f"Error generating MinIO upload URL: {e}")
            return None

    async def adownload_file(self, source_path: str, local_path: str) -> bool:
        """Download a file from MinIO to local path."""
        try:

            def _fget():
                self.client.fget_object(self.bucket_name, source_path, local_path)

            await asyncio.to_thread(_fget)
            return True
        except S3Error:
            return False

    async def acopy_file(self, source_path: str, destination_path: str) -> bool:
        """Copy a file within MinIO (server-side copy)."""
        try:
            from minio.commonconfig import CopySource

            def _copy():
                self.client.copy_object(
                    self.bucket_name,
                    destination_path,
                    CopySource(self.bucket_name, source_path),
                )

            await asyncio.to_thread(_copy)
            return True
        except S3Error:
            return False

    async def adelete_file(self, file_path: str) -> bool:
        """Delete an object from MinIO (missing objects count as deleted)."""
        try:
            await asyncio.to_thread(
                self.client.remove_object, self.bucket_name, file_path
            )
            return True
        except S3Error as error:
            if getattr(error, "code", "") in {"NoSuchKey", "NoSuchObject"}:
                return True
            logger.warning(f"MinIO delete failed for {file_path}: {error}")
            return False

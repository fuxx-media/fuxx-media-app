"""Private MinIO object storage with content-based validation."""

import asyncio
from dataclasses import dataclass
from io import BytesIO

from minio import Minio

from mediaos.application.errors import StoredFileNotFoundError, UploadValidationError
from mediaos.config import get_settings


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    content: bytes
    detected_mime_type: str


def validate_upload(content: bytes, claimed_mime_type: str | None) -> ValidatedUpload:
    settings = get_settings()
    if not content:
        raise UploadValidationError("Uploaded file is empty")
    if len(content) > settings.mediaos_upload_max_bytes:
        raise UploadValidationError(
            "Uploaded file exceeds the configured size limit",
            details={"max_bytes": settings.mediaos_upload_max_bytes},
        )
    detected: str | None = None
    if content.startswith(b"%PDF-"):
        detected = "application/pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif len(content) >= 12 and content[4:8] == b"ftyp":
        detected = "video/mp4"
    elif b"\x00" not in content:
        try:
            content.decode("utf-8")
            detected = "text/plain"
        except UnicodeDecodeError:
            detected = None
    if detected is None:
        raise UploadValidationError("File content type is not allowed or could not be verified")
    normalized_claim = (claimed_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized_claim != detected:
        raise UploadValidationError(
            "Claimed MIME type does not match verified file content",
            details={"claimed": normalized_claim, "detected": detected},
        )
    return ValidatedUpload(content=content, detected_mime_type=detected)


class ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        endpoint, secure = settings.minio_connection
        self.client = Minio(
            endpoint,
            access_key=settings.minio_root_user.get_secret_value(),
            secret_key=settings.minio_root_password.get_secret_value(),
            secure=secure,
        )

    async def put_private(
        self, *, bucket: str, object_key: str, content: bytes, content_type: str
    ) -> None:
        def _put() -> None:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
            self.client.put_object(
                bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type=content_type,
            )

        await asyncio.to_thread(_put)

    async def get_private(self, *, bucket: str, object_key: str) -> bytes:
        def _get() -> bytes:
            try:
                response = self.client.get_object(bucket, object_key)
            except Exception as exc:
                raise StoredFileNotFoundError("Stored object could not be read") from exc
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_get)

    async def remove(self, *, bucket: str, object_key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, bucket, object_key)

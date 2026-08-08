import io
import logging
import minio
from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = minio.Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def download_bytes(key: str) -> bytes | None:
    try:
        response = _get_client().get_object(settings.minio_bucket, key)
        return response.read()
    except minio.error.S3Error:
        return None


def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream"):
    _get_client().put_object(settings.minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type)

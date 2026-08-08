import io
import logging
from app.config import settings

logger = logging.getLogger(__name__)

_minio_client = None


def _get_client():
    global _minio_client
    if _minio_client is None:
        from minio import Minio
        _minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        _ensure_bucket(_minio_client)
    return _minio_client


def _ensure_bucket(client):
    import minio.error
    try:
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
    except minio.error.S3Error as e:
        if e.code != "BucketAlreadyOwnedByYou":
            raise


async def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream"):
    client = _get_client()
    client.put_object(settings.minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type)


async def download_bytes(key: str) -> bytes | None:
    from minio.error import S3Error
    client = _get_client()
    try:
        response = client.get_object(settings.minio_bucket, key)
        return response.read()
    except S3Error:
        return None

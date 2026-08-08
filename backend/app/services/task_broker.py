import logging
import redis
from app.config import settings

logger = logging.getLogger(__name__)

_redis = None

GPU_QUEUE = "gpu_queue"
STATUS_CHANNEL = "job_status"


def _get_redis():
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url)
    return _redis


def enqueue_gpu_job(job_id: str):
    r = _get_redis()
    r.rpush(GPU_QUEUE, job_id)
    logger.info(f"Enqueued job {job_id} to GPU queue")


def publish_status(job_id: str, status: str, progress: float = 0.0):
    import json
    r = _get_redis()
    r.publish(STATUS_CHANNEL, json.dumps({
        "job_id": job_id,
        "status": status,
        "progress": progress,
    }))

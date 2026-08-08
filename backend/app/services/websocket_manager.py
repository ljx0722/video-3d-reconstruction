import json
import logging
import asyncio
import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect
from app.config import settings

logger = logging.getLogger(__name__)


class JobStatusManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(job_id, []).append(ws)

    def disconnect(self, job_id: str, ws: WebSocket):
        if job_id in self._connections:
            self._connections[job_id] = [c for c in self._connections[job_id] if c != ws]
            if not self._connections[job_id]:
                del self._connections[job_id]

    async def broadcast(self, job_id: str, data: dict):
        for ws in self._connections.get(job_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = JobStatusManager()


async def redis_listener():
    """Listen for job status updates from Redis pub/sub and broadcast to WebSocket clients."""
    try:
        redis = await aioredis.from_url(settings.redis_url)
        pubsub = redis.pubsub()
        await pubsub.subscribe("job_status")
        logger.info("Redis listener started on channel: job_status")
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    job_id = data.get("job_id")
                    if job_id:
                        await manager.broadcast(job_id, data)
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        logger.error(f"Redis listener error: {e}")

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models.job import Base
from app.api.router import router
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database ready. Upload dir: {settings.upload_dir}")
    yield
    await engine.dispose()


app = FastAPI(title="Video2Gauss API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.websocket("/ws/{job_id}")
async def stream_ws(ws: WebSocket, job_id: str):
    """Live point cloud streaming WebSocket."""
    from app.api.gpu import _stream_connections
    await ws.accept()
    _stream_connections.setdefault(job_id, []).append(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except (WebSocketDisconnect, Exception):
        conns = _stream_connections.get(job_id, [])
        _stream_connections[job_id] = [w for w in conns if w != ws]
        if not _stream_connections[job_id]:
            _stream_connections.pop(job_id, None)

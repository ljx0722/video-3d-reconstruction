import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models.job import Base
from app.api.router import router
from app.services.websocket_manager import manager, redis_listener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_listener_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _listener_task
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    _listener_task = asyncio.create_task(redis_listener())
    yield
    if _listener_task:
        _listener_task.cancel()
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
    return {"status": "ok"}


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(ws: WebSocket, job_id: str):
    await manager.connect(job_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id, ws)
    except Exception:
        manager.disconnect(job_id, ws)

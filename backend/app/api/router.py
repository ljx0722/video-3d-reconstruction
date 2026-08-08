from fastapi import APIRouter
from app.api import jobs, files, gpu

router = APIRouter()
router.include_router(jobs.router, tags=["jobs"])
router.include_router(files.router, tags=["files"])
router.include_router(gpu.router, tags=["gpu"])

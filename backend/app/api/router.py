from fastapi import APIRouter
from app.api import jobs, files

router = APIRouter()
router.include_router(jobs.router, tags=["jobs"])
router.include_router(files.router, tags=["files"])

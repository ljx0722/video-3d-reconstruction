from fastapi import APIRouter
from app.api import files, gpu, gpu_mesh_runs, jobs, mesh_runs, mesh_sources

router = APIRouter()
router.include_router(jobs.router, tags=["jobs"])
router.include_router(mesh_runs.router, tags=["mesh-runs"])
router.include_router(files.router, tags=["files"])
router.include_router(gpu.router, tags=["gpu"])
router.include_router(gpu_mesh_runs.router, tags=["gpu-mesh-runs"])
router.include_router(mesh_sources.router, tags=["gpu-mesh-sources"])

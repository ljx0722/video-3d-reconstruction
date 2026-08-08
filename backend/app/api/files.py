from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.services import storage_service

router = APIRouter(prefix="/files")


@router.get("/{job_id}/result.glb")
async def get_result_file(job_id: str):
    key = f"results/{job_id}/pointcloud.glb"
    data = await storage_service.download_bytes(key)
    if data is None:
        raise HTTPException(status_code=404, detail="Result file not found")
    return StreamingResponse(
        iter([data]),
        media_type="model/gltf-binary",
        headers={
            "Content-Disposition": f"inline; filename={job_id}.glb",
            "Cache-Control": "public, max-age=86400",
        },
    )

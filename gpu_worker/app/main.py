import logging
import redis
import json
from app import infer, storage

logger = logging.getLogger(__name__)

GPU_QUEUE = "gpu_queue"
STATUS_CHANNEL = "job_status"


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info("GPU Worker starting...")

    r = redis.from_url(storage.settings.redis_url)

    while True:
        try:
            result = r.brpop(GPU_QUEUE, timeout=5)
            if result is None:
                continue

            _, job_id_bytes = result
            job_id = job_id_bytes.decode()
            logger.info(f"Processing job {job_id}")

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.1}))

            video_key = f"videos/{job_id}/raw.mp4"
            video_data = storage.download_bytes(video_key)
            if video_data is None:
                r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "failed", "error": "Video not found"}))
                continue

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.3}))

            settings = {"fps": 10, "mode": "streaming", "conf_threshold": 1.5}
            glb_data = infer.infer_video(video_data, settings)

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.8}))

            result_key = f"results/{job_id}/pointcloud.glb"
            storage.upload_bytes(glb_data, result_key, "model/gltf-binary")

            r.publish(STATUS_CHANNEL, json.dumps({
                "job_id": job_id, "status": "completed", "progress": 1.0,
                "result_url": f"/files/{job_id}/result.glb",
            }))
            logger.info(f"Job {job_id} completed")

        except Exception as e:
            logger.exception(f"Error processing job: {e}")
            try:
                r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "failed", "error": str(e)}))
            except Exception:
                pass


if __name__ == "__main__":
    main()

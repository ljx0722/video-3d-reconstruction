import logging
import redis
import json
from app import infer, storage, config

logger = logging.getLogger(__name__)

GPU_QUEUE = "gpu_queue"
STATUS_CHANNEL = "job_status"


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info("GPU Worker starting...")
    logger.info(f"Model path: {config.settings.model_path}")

    r = redis.from_url(config.settings.redis_url)

    while True:
        try:
            result = r.brpop(GPU_QUEUE, timeout=5)
            if result is None:
                continue

            _, job_id_bytes = result
            job_id = job_id_bytes.decode()
            logger.info(f"Processing job {job_id}")

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.05}))

            # Download video
            video_key = f"videos/{job_id}/raw.mp4"
            video_data = storage.download_bytes(video_key)
            if video_data is None:
                r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "failed", "error": "Video not found"}))
                continue

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.1}))

            # Download settings
            settings = {"fps": 10, "mode": "streaming", "conf_threshold": 1.5}
            settings_bytes = storage.download_bytes(f"videos/{job_id}/settings.json")
            if settings_bytes:
                try:
                    settings.update(json.loads(settings_bytes))
                except json.JSONDecodeError:
                    pass

            logger.info(f"Settings: {settings}")

            # Run inference
            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.15}))
            glb_data = infer.infer_video(video_data, settings, config.settings.model_path)

            r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "processing", "progress": 0.9}))

            # Upload result
            result_key = f"results/{job_id}/pointcloud.glb"
            storage.upload_bytes(glb_data, result_key, "model/gltf-binary")

            r.publish(STATUS_CHANNEL, json.dumps({
                "job_id": job_id, "status": "completed", "progress": 1.0,
                "result_url": f"/files/{job_id}/result.glb",
            }))
            logger.info(f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB GLB)")

        except Exception as e:
            logger.exception(f"Error processing job: {e}")
            try:
                r.publish(STATUS_CHANNEL, json.dumps({"job_id": job_id, "status": "failed", "error": str(e)}))
            except Exception:
                pass


if __name__ == "__main__":
    main()

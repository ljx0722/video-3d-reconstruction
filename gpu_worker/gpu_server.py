"""
GPU Worker server for lingbot-map. Runs on AutoDL GPU instance.
Polls Sealos backend for pending jobs, downloads videos, runs inference,
uploads GLB results back.

Usage:
    SEALOS_BACKEND_URL=https://video2gauss.sealoshzh.site python gpu_server.py
"""

import os
import sys
import time
import json
import tempfile
import logging
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gpu-worker")

BACKEND_URL = os.environ.get("SEALOS_BACKEND_URL", "https://video2gauss.sealoshzh.site").rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
CHECKPOINT_PATH = os.environ.get("MODEL_PATH", "./checkpoint/lingbot-map.pt")

# ── Model loading (lazy, loaded on first request) ──────────────────────────
_model = None
_device = None
_dtype = None


def load_model():
    global _model, _device, _dtype
    if _model is not None:
        return

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability()[0]
        _dtype = torch.bfloat16 if cap >= 8 else torch.float16
    else:
        _dtype = torch.float32

    from lingbot_map.models.gct_stream import GCTStream

    logger.info("Building GCTStream model...")
    _model = GCTStream(
        img_size=518, patch_size=14,
        enable_3d_rope=True, max_frame_num=1024,
        kv_cache_sliding_window=64, kv_cache_scale_frames=8,
        kv_cache_cross_frame_special=True, kv_cache_include_scale_frames=True,
        use_sdpa=True, camera_num_iterations=4,
    )

    ckpt_path = _find_checkpoint()
    logger.info(f"Loading checkpoint: {ckpt_path}")
    ckpt = torch.load(ckpt_path, map_location=_device, weights_only=False)
    state_dict = ckpt.get("model", ckpt)
    _model.load_state_dict(state_dict, strict=False)
    _model = _model.to(_device).eval()

    if _dtype != torch.float32 and hasattr(_model, "aggregator"):
        _model.aggregator = _model.aggregator.to(dtype=_dtype)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info(f"GPU mem: {torch.cuda.memory_allocated()/1e9:.2f} GB")


def _find_checkpoint():
    """Find the checkpoint file."""
    if os.path.isfile(CHECKPOINT_PATH):
        return CHECKPOINT_PATH
    # Check common locations
    for path in [
        "./checkpoint/lingbot-map.pt",
        "./checkpoint/model.pt",
        "./lingbot-map/checkpoint/lingbot-map.pt",
        "/root/autodl-tmp/checkpoint/lingbot-map.pt",
        "/root/autodl-fs/checkpoint/lingbot-map.pt",
    ]:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"Checkpoint not found at {CHECKPOINT_PATH}")


# ── Inference pipeline ──────────────────────────────────────────────────────
def process_video(video_path: str, settings: dict) -> str:
    """Run lingbot-map inference and export GLB. Returns GLB file path."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general

    load_model()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")
    conf_threshold = settings.get("conf_threshold", 1.5)

    # Extract frames
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = max(1, round(src_fps / fps))

    tmpdir = tempfile.mkdtemp()
    frame_paths = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval == 0:
            p = os.path.join(tmpdir, f"{len(frame_paths):06d}.jpg")
            cv2.imwrite(p, frame)
            frame_paths.append(p)
        idx += 1
    cap.release()

    num_frames = len(frame_paths)
    logger.info(f"Extracted {num_frames} frames (total={total_frames}, interval={interval})")

    # Preprocess
    images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
    images = images.to(_device)

    num_scale_frames = min(8, num_frames)
    if num_scale_frames >= num_frames:
        num_scale_frames = max(1, num_frames - 1)

    kf_interval = 1
    if mode == "streaming" and num_frames > 320:
        kf_interval = (num_frames + 319) // 320

    # Inference
    logger.info(f"Inference: {num_frames} frames, scale={num_scale_frames}, kf={kf_interval}")
    t0 = time.time()

    with torch.no_grad(), torch.amp.autocast("cuda", dtype=_dtype):
        if mode == "streaming":
            predictions = _model.inference_streaming(
                images, num_scale_frames=num_scale_frames, keyframe_interval=kf_interval
            )
        else:
            predictions = _model.inference_windowed(
                images, window_size=64, overlap_size=16, num_scale_frames=num_scale_frames
            )

    elapsed = time.time() - t0
    logger.info(f"Inference done in {elapsed:.1f}s")

    if torch.cuda.is_available():
        logger.info(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    # Postprocess
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])
    ext_4x4 = torch.zeros((*extrinsic.shape[:-2], 4, 4), device=extrinsic.device, dtype=extrinsic.dtype)
    ext_4x4[..., :3, :4] = extrinsic
    ext_4x4[..., 3, 3] = 1.0
    ext_4x4 = closed_form_inverse_se3_general(ext_4x4)  # c2w
    extrinsic = ext_4x4[..., :3, :4]  # (B, S, 3, 4)

    predictions["extrinsic"] = extrinsic
    predictions["intrinsic"] = intrinsic

    # Compute world_points_from_depth (needed for GLB export)
    if "world_points" not in predictions and "depth" in predictions:
        logger.info("Computing world_points_from_depth...")
        depth_t = predictions["depth"].clone()  # (B, S, H, W, 1)
        if depth_t.ndim == 5:
            depth_t = depth_t[0]  # (S, H, W, 1)
        S, H, W = depth_t.shape[0], depth_t.shape[1], depth_t.shape[2]

        # Get intrinsics
        intr = predictions["intrinsic"]
        if intr.ndim == 4:
            intr = intr[0]  # (S, 3, 3)

        # Get extrinsics (c2w)
        ext_t = predictions["extrinsic"]
        if ext_t.ndim == 4:
            ext_t = ext_t[0]  # (S, 3, 4)

        world_pts = []
        for si in range(S):
            d = depth_t[si, :, :, 0]  # (H, W)
            fx = intr[si, 0, 0].item()
            fy = intr[si, 1, 1].item()
            ppx = intr[si, 0, 2].item()
            ppy = intr[si, 1, 2].item()

            # Create pixel grid
            yy, xx = torch.meshgrid(
                torch.arange(H, device=depth_t.device),
                torch.arange(W, device=depth_t.device),
                indexing="ij",
            )
            xx = xx.float()
            yy = yy.float()

            # Camera-space coordinates
            z = d
            x = (xx - ppx) * z / fx
            y = (yy - ppy) * z / fy

            # Stack
            pts_cam = torch.stack([x, y, z], dim=-1).reshape(-1, 3)  # (H*W, 3)

            # Transform to world using extrinsics (c2w)
            R = ext_t[si, :, :3]  # (3, 3)
            T = ext_t[si, :, 3]   # (3,)
            pts_w = pts_cam @ R.T + T

            world_pts.append(pts_w.reshape(H, W, 3))

        predictions["world_points_from_depth"] = torch.stack(world_pts, dim=0).unsqueeze(0)  # (1, S, H, W, 3)
        logger.info("world_points_from_depth computed")

    # Move to CPU and convert to numpy
    vis_pred = {}
    for k, v in predictions.items():
        if isinstance(v, torch.Tensor):
            v_np = v.cpu().numpy()
            if v_np.ndim >= 3 and v_np.shape[0] == 1:
                v_np = v_np[0]
            vis_pred[k] = v_np
        elif isinstance(v, np.ndarray):
            vis_pred[k] = v
        else:
            vis_pred[k] = v

    imgs_np = images.cpu().numpy()
    if imgs_np.ndim >= 4 and imgs_np.shape[0] == 1:
        imgs_np = imgs_np[0]
    vis_pred["images"] = imgs_np

    del images, predictions
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Export GLB
    from lingbot_map.vis.glb_export import predictions_to_glb

    glb_path = os.path.join(tmpdir, "output.glb")
    scene = predictions_to_glb(vis_pred, conf_thres=conf_threshold, show_cam=True, mask_sky=False)
    scene.export(glb_path)

    size_mb = os.path.getsize(glb_path) / (1024 * 1024)
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s")

    return glb_path


# ── Job polling loop ────────────────────────────────────────────────────────
def poll_and_process():
    """Main loop: poll for pending jobs, process them, upload results."""
    logger.info(f"GPU Worker starting, backend={BACKEND_URL}")

    # Check cp exists (model loaded lazily on first job)
    _find_checkpoint()
    logger.info("GPU Worker ready, polling for jobs...")

    while True:
        try:
            # Get pending jobs from backend
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/pending",
                headers={"User-Agent": "gpu-worker/1.0"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            jobs = json.loads(resp.read())
        except Exception as e:
            logger.warning(f"Failed to poll pending jobs: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if not jobs:
            time.sleep(POLL_INTERVAL)
            continue

        for job in jobs:
            job_id = job["id"]
            logger.info(f"Processing job {job_id}...")

            try:
                # Download video
                video_req = urllib.request.Request(
                    f"{BACKEND_URL}/api/v1/gpu/video/{job_id}",
                    headers={"User-Agent": "gpu-worker/1.0"},
                )
                video_resp = urllib.request.urlopen(video_req, timeout=60)
                video_data = video_resp.read()

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(video_data)
                    video_tmp = f.name

                # Get settings
                settings = job.get("settings", {"fps": 10, "mode": "streaming", "conf_threshold": 1.5})
                if isinstance(settings, str):
                    settings = json.loads(settings)

                # Update status to processing
                _update_status(job_id, "processing", 0.1)

                # Run inference
                glb_path = process_video(video_tmp, settings)
                os.unlink(video_tmp)

                # Upload GLB result
                with open(glb_path, "rb") as f:
                    glb_data = f.read()

                _update_status(job_id, "processing", 0.9)
                _upload_result(job_id, glb_data)

                # Clean up
                os.unlink(glb_path)
                logger.info(f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB)")

            except Exception as e:
                logger.exception(f"Job {job_id} failed")
                try:
                    _update_status(job_id, "failed", 0, error=str(e)[:500])
                except Exception:
                    pass

        time.sleep(POLL_INTERVAL)


def _update_status(job_id: str, status: str, progress: float, error: str = ""):
    data = json.dumps({"status": status, "progress": progress, "error_message": error}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/gpu/status/{job_id}",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "gpu-worker/1.0"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _upload_result(job_id: str, glb_data: bytes):
    boundary = "----GPUWorkerUpload"
    body = (
        b"--" + boundary.encode() + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="result.glb"\r\n'
        b"Content-Type: model/gltf-binary\r\n\r\n"
        + glb_data + b"\r\n"
        b"--" + boundary.encode() + b"--\r\n"
    )
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/gpu/result/{job_id}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "gpu-worker/1.0"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=120)


if __name__ == "__main__":
    poll_and_process()

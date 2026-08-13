"""
GPU Worker server for lingbot-map. Runs on AutoDL GPU instance.
Polls Sealos backend for pending jobs, downloads videos, runs inference,
uploads GLB results back.

Usage:
    SEALOS_BACKEND_URL=https://video2gauss.sealoshzh.site python gpu_server.py
"""

import hashlib
import io
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gpu-worker")

BACKEND_URL = os.environ.get("SEALOS_BACKEND_URL", "https://video2gauss.sealoshzh.site").rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
CHECKPOINT_PATH = os.environ.get("MODEL_PATH") or os.environ.get("CHECKPOINT_PATH") or "/root/autodl-tmp/lingbot-map.pt"
GPU_SECRET = os.environ.get("GPU_SECRET", "")
WORKER_ID = os.environ.get("GPU_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
ARTIFACT_VERSION = 2
ARTIFACT_ALIGNMENT = "first-camera-opengl-y180"
LEGACY_INLINE_MESH = os.environ.get("LEGACY_INLINE_MESH", "0") == "1"


def _clamp_conf_percentile(value, default: float = 1.5) -> float:
    """Return a finite user confidence percentile clamped to [0, 100]."""
    import math

    try:
        percentile = float(value)
    except (TypeError, ValueError):
        percentile = default
    if not math.isfinite(percentile):
        percentile = default
    return max(0.0, min(100.0, percentile))


def _artifact_metadata(settings: dict | None = None) -> dict:
    """Build public artifact metadata without copying request settings or secrets."""
    metadata = {
        "version": ARTIFACT_VERSION,
        "alignment": ARTIFACT_ALIGNMENT,
        "color_space": "linear-srgb",
    }
    if settings is not None:
        metadata.update({
            "confidence_percentile": _clamp_conf_percentile(
                settings.get("_conf_pct", settings.get("conf_threshold", 1.5))
            ),
            "spatial_stride": int(settings.get("_dynamic_stride", 1)),
            "keyframes": int(settings.get("_artifact_keyframes", 0)),
        })
    return metadata


def _worker_headers(**extra: str) -> dict[str, str]:
    headers = {"User-Agent": "gpu-worker/1.0", **extra}
    if GPU_SECRET:
        headers["Authorization"] = f"Bearer {GPU_SECRET}"
    return headers

def _mesh_headers(lease_token: str | None = None, **extra: str) -> dict[str, str]:
    headers = _worker_headers(**extra)
    if lease_token:
        headers["X-Mesh-Lease-Token"] = lease_token
    return headers


def _mesh_request(
    path: str,
    method: str = "GET",
    payload: dict | bytes | None = None,
    lease_token: str | None = None,
    timeout: int = 30,
):
    data = None
    headers = _mesh_headers(lease_token)
    if isinstance(payload, dict):
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif isinstance(payload, bytes):
        data = payload
        headers["Content-Type"] = "application/octet-stream"
    request = urllib.request.Request(
        f"{BACKEND_URL}{path}", data=data, headers=headers, method=method
    )
    return urllib.request.urlopen(request, timeout=timeout)


class MeshLeaseHeartbeat:
    def __init__(self, run_id: str, lease_token: str):
        self.run_id = run_id
        self.lease_token = lease_token
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.ownership_lost = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self) -> None:
        while not self.stop_event.wait(45):
            try:
                response = _mesh_request(
                    f"/api/v1/gpu/mesh-runs/{self.run_id}/heartbeat",
                    method="POST",
                    payload={},
                    lease_token=self.lease_token,
                    timeout=15,
                )
                data = json.loads(response.read())
                if data.get("cancel_requested"):
                    self.cancel_event.set()
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 404, 409}:
                    self.ownership_lost.set()
                    self.cancel_event.set()
                    return
                logger.warning("Mesh heartbeat failed for %s: %s", self.run_id, exc)
            except Exception as exc:
                logger.warning("Mesh heartbeat failed for %s: %s", self.run_id, exc)


def _mesh_status(
    run_id: str,
    lease_token: str,
    status: str = "processing",
    progress: float | None = None,
    detail: str | None = None,
    stats: dict | None = None,
    error_message: str | None = None,
) -> None:
    payload = {"status": status}
    if progress is not None:
        payload["progress"] = progress
    if detail is not None:
        payload["detail"] = detail
    if stats is not None:
        payload["stats"] = stats
    if error_message is not None:
        payload["error_message"] = error_message
    _mesh_request(
        f"/api/v1/gpu/mesh-runs/{run_id}/status",
        method="POST",
        payload=payload,
        lease_token=lease_token,
        timeout=30,
    ).read()


def _claim_mesh_run() -> dict | None:
    try:
        response = _mesh_request(
            "/api/v1/gpu/mesh-runs/claim",
            method="POST",
            payload={"worker_id": WORKER_ID},
            timeout=15,
        )
        if response.status == 204:
            return None
        return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _load_tsdf_colors(video_path: str, frame_indices, height: int, width: int):
    import cv2
    import numpy as np
    import torch
    from lingbot_map.utils.load_fn import load_and_preprocess_images

    requested = [int(value) for value in np.asarray(frame_indices).reshape(-1)]
    if not requested:
        return np.empty((0, height, width, 3), dtype=np.float32)
    frame_paths = []
    with tempfile.TemporaryDirectory() as directory:
        capture = cv2.VideoCapture(video_path)
        try:
            for index, source_index in enumerate(requested):
                capture.set(cv2.CAP_PROP_POS_FRAMES, source_index)
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(f"Unable to decode source video frame {source_index}")
                path = os.path.join(directory, f"{index:04d}.jpg")
                cv2.imwrite(path, frame)
                frame_paths.append(path)
        finally:
            capture.release()
        images = load_and_preprocess_images(
            frame_paths, mode="crop", image_size=518, patch_size=14
        )
        values = images.detach().cpu().permute(0, 2, 3, 1).numpy().astype(np.float32)
    if values.shape[1:3] != (height, width):
        raise RuntimeError(
            f"Preprocessed color shape {values.shape[1:3]} does not match sidecar {(height, width)}"
        )
    return values


def _process_tsdf_mesh_run(run: dict, heartbeat: MeshLeaseHeartbeat, source_response):
    import numpy as np

    manifest = json.loads(source_response.read())
    if manifest.get("manifest_sha256") != run["source_sha256"]:
        raise RuntimeError("Mesh source manifest checksum mismatch")
    video_response = _mesh_request(
        f"/api/v1/gpu/video/{run['job_id']}", timeout=300
    )
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as target:
        while True:
            block = video_response.read(1024 * 1024)
            if not block:
                break
            target.write(block)
        video_path = target.name

    try:
        try:
            from tsdf_builder import build_tsdf_mesh
        except ImportError:
            from gpu_worker.tsdf_builder import build_tsdf_mesh

        def chunk_loader(entry):
            response = _mesh_request(
                f"/api/v1/gpu/mesh-runs/{run['id']}/source/chunks/{entry['name']}",
                lease_token=run["lease_token"],
                timeout=300,
            )
            data = response.read()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise RuntimeError(f"Mesh source chunk checksum mismatch: {entry['name']}")
            return data

        def color_loader(frame_indices, height, width):
            return _load_tsdf_colors(video_path, frame_indices, height, width)

        config = run.get("config", {})
        chunk_cache: dict[str, bytes] = {}
        mask_store = None
        if config.get("use_sam2"):
            try:
                from sam2_mask import build_sam2_mask_store
            except ImportError:
                from gpu_worker.sam2_mask import build_sam2_mask_store

            def sam2_progress(progress, detail):
                if heartbeat.ownership_lost.is_set():
                    return
                try:
                    _mesh_status(run["id"], run["lease_token"], progress=0.05 + 0.4 * progress, detail=detail)
                except Exception as exc:
                    logger.warning("SAM2 progress update failed for %s: %s", run["id"], exc)

            entries = manifest.get("chunks", [])
            requested_indices = []
            for entry in entries:
                data = chunk_loader(entry)
                chunk_cache[entry["name"]] = data
                with np.load(io.BytesIO(data), allow_pickle=False) as loaded:
                    requested_indices.extend(int(value) for value in loaded["frame_indices"])
            mask_store = build_sam2_mask_store(
                video_path,
                config.get("sam2_prompts", []),
                requested_indices,
                manifest["image_height"],
                manifest["image_width"],
                progress_callback=sam2_progress,
                cancel_check=lambda: heartbeat.cancel_event.is_set(),
            )

        def cached_chunk_loader(entry):
            cached = chunk_cache.get(entry["name"])
            if cached is not None:
                return cached
            return chunk_loader(entry)

        def mask_loader(frame_indices, height, width):
            return mask_store.load(frame_indices, height, width)

        def progress_callback(progress, detail):
            if heartbeat.ownership_lost.is_set():
                return
            try:
                _mesh_status(run["id"], run["lease_token"], progress=progress, detail=detail)
            except Exception as exc:
                logger.warning("TSDF progress update failed for %s: %s", run["id"], exc)

        return build_tsdf_mesh(
            manifest,
            cached_chunk_loader,
            color_loader,
            config,
            progress_callback=progress_callback,
            cancel_check=lambda: heartbeat.cancel_event.is_set(),
            mask_loader=mask_loader if mask_store else None,
        )
    finally:
        os.unlink(video_path)


def _process_mesh_run(run: dict) -> None:
    run_id = run["id"]
    lease_token = run["lease_token"]
    heartbeat = MeshLeaseHeartbeat(run_id, lease_token)
    heartbeat.start()
    try:
        _mesh_status(run_id, lease_token, progress=0.02, detail="正在下载点云源文件")
        source_response = _mesh_request(
            run["source_url"], lease_token=lease_token, timeout=300
        )
        if run.get("source_kind") == "mesh-source-v1":
            result = _process_tsdf_mesh_run(run, heartbeat, source_response)
        else:
            source_data = source_response.read()
            actual_hash = hashlib.sha256(source_data).hexdigest()
            if actual_hash != run["source_sha256"]:
                raise RuntimeError("Mesh source checksum mismatch")

            try:
                from mesh_builder import build_mesh, extract_legacy_point_glb
            except ImportError:
                from gpu_worker.mesh_builder import build_mesh, extract_legacy_point_glb

            vis_pred, source_stats = extract_legacy_point_glb(
                source_data, run.get("source_color_space", "srgb")
            )

            def progress_callback(progress: float, detail: str) -> None:
                if heartbeat.ownership_lost.is_set():
                    return
                try:
                    _mesh_status(run_id, lease_token, progress=progress, detail=detail)
                except Exception as exc:
                    logger.warning("Mesh progress update failed for %s: %s", run_id, exc)

            with tempfile.TemporaryDirectory() as tmpdir:
                result = build_mesh(
                    vis_pred,
                    0,
                    tmpdir,
                    config=run.get("config"),
                    progress_callback=progress_callback,
                    cancel_check=lambda: heartbeat.cancel_event.is_set(),
                )
            result.stats.update(source_stats)
        if heartbeat.ownership_lost.is_set():
            logger.warning("MeshRun %s lease lost; discarding output", run_id)
            return
        if heartbeat.cancel_event.is_set():
            _mesh_status(
                run_id, lease_token, status="cancelled", detail="已取消", stats=result.stats
            )
            return
        if not result.success:
            _mesh_status(
                run_id,
                lease_token,
                status="failed",
                detail="表面重建失败",
                stats=result.stats,
                error_message=result.error,
            )
            return
        _mesh_request(
            f"/api/v1/gpu/mesh-runs/{run_id}/result",
            method="POST",
            payload=result.data,
            lease_token=lease_token,
            timeout=300,
        ).read()
        logger.info("MeshRun %s completed: %s", run_id, result.stats)
    except Exception as exc:
        logger.exception("MeshRun %s failed", run_id)
        if not heartbeat.ownership_lost.is_set():
            try:
                _mesh_status(
                    run_id,
                    lease_token,
                    status="cancelled" if heartbeat.cancel_event.is_set() else "failed",
                    detail="已取消" if heartbeat.cancel_event.is_set() else "表面重建失败",
                    error_message=str(exc)[:2000],
                )
            except Exception:
                pass
    finally:
        heartbeat.stop()
        import gc
        gc.collect()
        try:
            import torch as _torch
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass


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
        enable_3d_rope=True, max_frame_num=512,
        kv_cache_sliding_window=64, kv_cache_scale_frames=4,
        kv_cache_cross_frame_special=True, kv_cache_include_scale_frames=True,
        use_sdpa=True, camera_num_iterations=4,
    )

    ckpt_path = _find_checkpoint()
    logger.info(f"Loading checkpoint: {ckpt_path}")
    # weights_only=False required for GCTStream custom model classes
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
def process_video(video_path: str, settings: dict, job_id: str):
    """Run lingbot-map inference and return point-cloud GLB plus Mesh inputs."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general

    load_model()

    # Update progress now that model is loaded (took ~15-20s for 7GB checkpoint)
    _update_status(job_id, "processing", 0.11, "模型已加载, 开始处理视频...")

    t_start = time.time()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")

    # ── Extract frames ─────────────────────────────────────────────────
    _update_status(job_id, "processing", 0.12, "正在解码视频帧...")

    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    video_duration = total_frames / src_fps if src_fps > 0 else 0

    # ── Adaptive quality strategy ──────────────────────────────────────
    # Goal: approach "manual frame selection" quality — extract frames close to
    # user-requested FPS, use stride=1 for short scenes, keep most confidence points.
    #
    # Point budget per keyframe: stride=1→268K, stride=2→67K, stride=3→30K
    # GLB winner-take-all dedup removes ~40-60% overlap, so actual ~half.
    #
    # max_target and max_keyframes are frame caps; stride controls spatial density.
    # Confidence filtering remains a user setting and is not duration-dependent.

    if video_duration < 10:
        max_target, stride, max_keyframes = 300, 1, 60
    elif video_duration < 20:
        max_target, stride, max_keyframes = 400, 1, 80
    elif video_duration < 30:
        max_target, stride, max_keyframes = 450, 1, 100
    elif video_duration < 45:
        max_target, stride, max_keyframes = 500, 2, 80
    elif video_duration < 60:
        max_target, stride, max_keyframes = 500, 2, 100
    elif video_duration < 90:
        max_target, stride, max_keyframes = 550, 2, 120
    elif video_duration < 150:
        max_target, stride, max_keyframes = 600, 2, 150
    else:
        max_target, stride, max_keyframes = 600, 2, 180
    conf_pct = _clamp_conf_percentile(settings.get("conf_threshold", 1.5))

    desired_fps = fps
    interval = max(1, round(src_fps / desired_fps))
    estimated_frames = total_frames // interval
    if estimated_frames > max_target:
        desired_fps = max(1, src_fps * max_target / total_frames)
        interval = max(1, round(src_fps / desired_fps))
        estimated_frames = total_frames // interval
        logger.info(f"Video {video_duration:.0f}s: {total_frames} total → ~{estimated_frames} frames (dynamic cap)")
    else:
        logger.info(f"Video {video_duration:.0f}s: {total_frames} total → ~{estimated_frames} frames")

    # Store for GLB export
    settings["_dynamic_stride"] = stride
    settings["_max_keyframes"] = max_keyframes
    settings["_conf_pct"] = conf_pct

    tmpdir = tempfile.mkdtemp()
    frame_paths = []
    frame_indices = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        if idx % interval == 0:
            p = os.path.join(tmpdir, f"{len(frame_paths):06d}.jpg")
            cv2.imwrite(p, frame)
            frame_paths.append(p)
            frame_indices.append(idx)
        idx += 1
    cap.release()

    num_frames = len(frame_paths)
    logger.info(f"Extracted {num_frames} frames (total={total_frames}, interval={interval})")

    # ── Preprocess (exactly as demo.py) ─────────────────────────────────
    _update_status(job_id, "processing", 0.15, f"预处理 {num_frames} 帧图像...")
    images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
    images = images.to(_device)

    num_scale_frames = min(4, num_frames)
    if num_scale_frames >= num_frames:
        num_scale_frames = max(1, num_frames - 1)

    kf_interval = 1
    if mode == "streaming" and num_frames > 320:
        kf_interval = (num_frames + 319) // 320

    # ── Inference (exactly as demo.py) ──────────────────────────────────
    logger.info(f"Inference: {num_frames} frames, scale={num_scale_frames}, kf={kf_interval}")
    est_time = num_frames / 5.0  # ~5 FPS estimate
    _update_status(job_id, "processing", 0.12, f"GPU 推理 {num_frames} 帧中, 预计 {est_time:.0f}s...")
    t0 = time.time()

    with torch.no_grad(), torch.amp.autocast("cuda", dtype=_dtype):
        if mode == "streaming":
            predictions = _model.inference_streaming(
                images, num_scale_frames=num_scale_frames, keyframe_interval=kf_interval,
            )
        else:
            predictions = _model.inference_windowed(
                images, window_size=64, overlap_size=16, num_scale_frames=num_scale_frames,
            )

    elapsed = time.time() - t0
    logger.info(f"Inference done in {elapsed:.1f}s")
    if torch.cuda.is_available():
        logger.info(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
        torch.cuda.reset_peak_memory_stats()

    # Free GPU images after extracting shape info for postprocess
    img_h, img_w = images.shape[-2], images.shape[-1]
    del images
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ── Postprocess (exactly as demo.py) ────────────────────────────────
    # Convert pose encoding to extrinsic/intrinsic
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], (img_h, img_w))
    # w2c → c2w
    ext_4x4 = torch.zeros((*extrinsic.shape[:-2], 4, 4), device=extrinsic.device, dtype=extrinsic.dtype)
    ext_4x4[..., :3, :4] = extrinsic
    ext_4x4[..., 3, 3] = 1.0
    ext_4x4 = closed_form_inverse_se3_general(ext_4x4)
    extrinsic = ext_4x4[..., :3, :4]
    predictions["extrinsic"] = extrinsic
    predictions["intrinsic"] = intrinsic

    # Remove batch dimension and move to CPU (demo.py postprocess)
    _BATCHED_NDIMS = {"pose_enc": 3, "depth": 5, "depth_conf": 4, "world_points": 5, "world_points_conf": 4, "extrinsic": 4, "intrinsic": 4, "images": 5}
    def _squeeze(k, v):
        nd = _BATCHED_NDIMS.get(k)
        if nd is None or not hasattr(v, "ndim"): return v
        if v.ndim == nd and v.shape[0] == 1: return v[0]
        return v

    logger.info("Moving results to CPU...")
    for k in list(predictions.keys()):
        if isinstance(predictions[k], torch.Tensor):
            predictions[k] = _squeeze(k, predictions[k].to("cpu", non_blocking=True))
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    predictions.pop("pose_enc_list", None)
    # Images are already moved to CPU in predictions, keep them there
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ── Prepare for visualization (exactly as demo.py prepare_for_visualization) ──
    vis_pred = {}
    for k, v in predictions.items():
        if isinstance(v, torch.Tensor):
            v_np = _squeeze(k, v.detach().cpu()).numpy() if v.ndim >= 1 else v.numpy()
        elif isinstance(v, np.ndarray):
            v_np = _squeeze(k, v)
        else:
            v_np = v
        vis_pred[k] = v_np

    # images are in predictions dict, already moved to CPU
    imgs_np = vis_pred.get("images")
    if imgs_np is not None:
        vis_pred["images"] = imgs_np

    # ── Build high-quality Mesh sidecar before display downsampling ────
    try:
        from mesh_source import build_mesh_source_package
    except ImportError:
        from gpu_worker.mesh_source import build_mesh_source_package

    sidecar_inputs = {
        key: vis_pred.get(key)
        for key in ("depth", "depth_conf", "world_points_conf", "intrinsic", "extrinsic")
        if vis_pred.get(key) is not None
    }

    # ── Compute world points AND stream per-batch to frontend ──────────
    if "world_points" not in vis_pred:
        logger.info("Computing world_points_from_depth...")
        from lingbot_map.utils.geometry import unproject_depth_map_to_point_map
        depth_t = vis_pred["depth"]; extrinsics = vis_pred["extrinsic"]; intrinsics = vis_pred["intrinsic"]
        world_pts = unproject_depth_map_to_point_map(depth_t, extrinsics, intrinsics)
        vis_pred["world_points_from_depth"] = world_pts

    _update_status(job_id, "processing", 0.85, "导出GLB模型...")
    from lingbot_map.vis.glb_export import compute_scene_alignment, predictions_to_glb

    stride = settings.get("_dynamic_stride", 2)
    max_kf = settings.get("_max_keyframes", 50)
    conf_pct_val = settings.get("_conf_pct", 20)

    # Spatial downsampling
    vis_pred_sub = {}
    for k, v in vis_pred.items():
        if k in ("world_points_from_depth", "world_points") and v.ndim >= 4:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k == "depth" and v.ndim >= 3:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k in ("depth_conf", "world_points_conf") and v is not None and v.ndim >= 3:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k == "images" and v.ndim >= 4:
            vis_pred_sub[k] = v[:, :, ::stride, ::stride] if v.shape[1] == 3 else v[:, ::stride, ::stride, ...]
        else:
            vis_pred_sub[k] = v

    # Temporally subsample to max_keyframes
    num_frames_full = vis_pred_sub.get("depth", vis_pred.get("depth", np.zeros(1))).shape[0]
    if num_frames_full > max_kf:
        kf_step = max(2, int(np.ceil(num_frames_full / max_kf)))
        for key in list(vis_pred_sub.keys()):
            v = vis_pred_sub[key]
            if isinstance(v, np.ndarray) and v.ndim >= 3 and v.shape[0] == num_frames_full:
                vis_pred_sub[key] = v[::kf_step]
        nf = vis_pred_sub.get("depth", vis_pred.get("depth", np.zeros(1))).shape[0]
        logger.info(f"Temporal subsample: {num_frames_full} keyframes → {nf} (step={kf_step})")

    # Compute the alignment from the exact temporally-subsampled extrinsics that
    # predictions_to_glb consumes, then share it with the Mesh artifact.
    selected_extrinsics = np.asarray(vis_pred_sub["extrinsic"])
    extrinsics_4x4 = np.zeros((len(selected_extrinsics), 4, 4), dtype=selected_extrinsics.dtype)
    extrinsics_4x4[:, :3, :4] = selected_extrinsics
    extrinsics_4x4[:, 3, 3] = 1.0
    alignment_matrix = compute_scene_alignment(extrinsics_4x4)

    mesh_source_uploaded = False
    try:
        _update_status(job_id, "processing", 0.86, "正在上传高质量表面数据...")
        try:
            from mesh_source import upload_mesh_source_package
        except ImportError:
            from gpu_worker.mesh_source import upload_mesh_source_package
        sidecar_package = build_mesh_source_package(
            sidecar_inputs,
            np.asarray(frame_indices, dtype=np.int32),
            alignment_matrix,
            source_video={
                "source_fps": float(src_fps),
                "source_frame_count": total_frames,
                "source_height": source_height,
                "source_width": source_width,
            },
        )
        upload_result = upload_mesh_source_package(
            BACKEND_URL,
            job_id,
            sidecar_package,
            _worker_headers,
        )
        mesh_source_uploaded = True
        settings["_mesh_source"] = {
            "version": "mesh-source-v1",
            "frame_count": sidecar_package.manifest["frame_count"],
            "chunk_count": sidecar_package.manifest["chunk_count"],
            "manifest_sha256": upload_result.get("manifest_sha256"),
        }
        del sidecar_package
    except Exception as exc:
        logger.warning("mesh-source-v1 upload failed for %s: %s", job_id, exc)
        settings["_mesh_source_error"] = str(exc)[:500]
    finally:
        del sidecar_inputs

    glb_path = os.path.join(tmpdir, "output.glb")
    scene = predictions_to_glb(vis_pred_sub, conf_thres=conf_pct_val, show_cam=True, mask_sky=False)
    scene.export(glb_path)
    with open(glb_path, "rb") as f:
        glb_data = f.read()

    # Count points for reporting (ensure Python int, not numpy)
    total_pts = 0
    for name in scene.geometry:
        if hasattr(scene.geometry[name], 'vertices'):
            total_pts += int(scene.geometry[name].vertices.shape[0])

    import shutil as _shutil
    _shutil.rmtree(tmpdir, ignore_errors=True)

    size_mb = len(glb_data) / (1024 * 1024)
    total_elapsed = time.time() - t_start
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s (total={total_elapsed:.0f}s)")

    settings["_num_frames"] = num_frames
    settings["_artifact_keyframes"] = len(selected_extrinsics)
    settings["_total_elapsed"] = total_elapsed
    settings["_num_points"] = total_pts
    settings["_artifact_metadata"] = _artifact_metadata(settings)

    return glb_data, vis_pred_sub, conf_pct_val, alignment_matrix

def poll_and_process():
    """Main loop: poll for pending jobs, process them, upload results."""
    if not GPU_SECRET or GPU_SECRET == "gpu-worker-secret":
        raise RuntimeError("GPU_SECRET must be configured with a non-default value")
    logger.info(f"GPU Worker starting, backend={BACKEND_URL}")

    # Check cp exists (model loaded lazily on first job)
    _find_checkpoint()
    logger.info("GPU Worker ready, polling for jobs...")

    while True:
        try:
            # Get pending jobs from backend
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/pending",
                headers=_worker_headers(),
            )
            resp = urllib.request.urlopen(req, timeout=10)
            jobs = json.loads(resp.read())
        except Exception as e:
            logger.warning(f"Failed to poll pending jobs: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if not jobs:
            try:
                mesh_run = _claim_mesh_run()
                if mesh_run:
                    logger.info("Processing MeshRun %s for job %s", mesh_run["id"], mesh_run["job_id"])
                    _process_mesh_run(mesh_run)
                    continue
            except Exception as exc:
                logger.warning("Failed to claim MeshRun: %s", exc)
            time.sleep(POLL_INTERVAL)
            continue

        for job in jobs:
            job_id = job["id"]
            logger.info(f"Processing job {job_id}...")

            try:
                point_cloud_uploaded = False
                # Download video with retry + backoff
                video_data = None
                last_err = None
                for retry in range(5):
                    try:
                        _update_status(job_id, "processing", 0.02,
                                       f"从后端下载视频{'' if retry==0 else f'重试{retry}/5'}..." if retry==0 else f"下载重试{retry}/5...")
                        video_req = urllib.request.Request(
                            f"{BACKEND_URL}/api/v1/gpu/video/{job_id}",
                            headers=_worker_headers(),
                        )
                        # Read in 32KB chunks with socket-level read timeout
                        resp = urllib.request.urlopen(video_req, timeout=120)
                        chunks = []
                        total = 0
                        while True:
                            chunk = resp.read(32768)
                            if not chunk: break
                            chunks.append(chunk)
                            total += len(chunk)
                            # Log progress for large videos
                            if retry == 0 and total % (5 * 1024 * 1024) < 32768:
                                _update_status(job_id, "processing", 0.04, f"下载视频 {total//(1024*1024)}MB...")
                        video_data = b''.join(chunks)
                        resp.close()
                        logger.info(f"Downloaded {len(video_data)/1024/1024:.1f} MB")
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning(f"Download attempt {retry+1}/5 failed: {e}")
                        if retry < 4:
                            time.sleep(2 + retry * retry)  # 2s, 3s, 6s, 11s backoff
                        continue
                if video_data is None:
                    raise last_err or Exception("Video download failed after 5 retries")

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(video_data)
                    video_tmp = f.name

                # Get settings
                settings = job.get("settings", {"fps": 10, "mode": "streaming", "conf_threshold": 1.5})
                if isinstance(settings, str):
                    settings = json.loads(settings)

                # Update status to processing
                _update_status(job_id, "processing", 0.1)

                # Run inference and export the point cloud before starting Mesh reconstruction.
                glb_data, mesh_inputs, mesh_conf_pct, alignment_matrix = process_video(
                    video_tmp, settings, job_id
                )
                os.unlink(video_tmp)

                _update_status(job_id, "processing", 0.9, "上传点云模型...")
                _upload_result(job_id, glb_data)
                point_cloud_uploaded = True

                if not LEGACY_INLINE_MESH:
                    nf = settings.get("_num_frames", 0)
                    te = settings.get("_total_elapsed", 0)
                    np_pts = settings.get("_num_points", 0)
                    _update_status(
                        job_id,
                        "completed",
                        1.0,
                        "点云重建完成，表面重建已独立排队",
                        num_frames=nf,
                        processing_time_secs=te,
                        num_points=np_pts,
                        artifact_metadata=settings.get("_artifact_metadata"),
                    )
                    del glb_data
                    del mesh_inputs
                    import gc
                    gc.collect()
                    try:
                        import torch as _torch
                        _torch.cuda.empty_cache()
                        _torch.cuda.reset_peak_memory_stats()
                    except Exception:
                        pass
                    logger.info("Job %s point artifact completed; MeshRun queued", job_id)
                    continue

                _update_status(
                    job_id,
                    "processing",
                    0.92,
                    "正在生成 Mesh 模型...",
                    num_frames=settings.get("_num_frames", 0),
                    num_points=settings.get("_num_points", 0),
                    processing_time_secs=settings.get("_total_elapsed", 0),
                    artifact_metadata=settings.get("_artifact_metadata"),
                )
                try:
                    from mesh_builder import build_mesh
                except ImportError:
                    from gpu_worker.mesh_builder import build_mesh
                mesh_inputs["alignment_matrix"] = alignment_matrix
                with tempfile.TemporaryDirectory() as mesh_tmpdir:
                    mesh_result = build_mesh(mesh_inputs, mesh_conf_pct, mesh_tmpdir)
                if mesh_result.success:
                    if not mesh_result.stats.get("alignment_applied"):
                        raise RuntimeError("Mesh builder did not apply the artifact alignment matrix")
                    mesh_result.stats["glb_bytes"] = len(mesh_result.data)
                else:
                    mesh_result.stats["alignment_applied"] = False
                settings["_mesh_stats"] = mesh_result.stats
                del mesh_inputs

                # Finalize independently so a valid point cloud remains viewable if Mesh fails.
                nf = settings.get("_num_frames", 0)
                te = settings.get("_total_elapsed", 0)
                np_pts = settings.get("_num_points", 0)
                mesh_stats = settings.get("_mesh_stats", {})
                if not mesh_result.success:
                    mesh_error = f"Mesh 生成失败: {mesh_result.error}"
                    _update_status(
                        job_id,
                        "partial",
                        0.9,
                        mesh_error,
                        num_frames=nf,
                        processing_time_secs=te,
                        num_points=np_pts,
                        artifact_metadata=settings.get("_artifact_metadata"),
                        mesh_stats=mesh_stats,
                    )
                    logger.warning("Job %s completed with point cloud only: %s", job_id, mesh_error)
                    mesh_data = b""
                else:
                    mesh_data = mesh_result.data
                    _update_status(job_id, "processing", 0.95, "上传 Mesh 模型...")
                    _upload_mesh(job_id, mesh_data)
                    mesh_faces = mesh_stats.get("mesh_triangles", 0)
                    _update_status(
                        job_id,
                        "completed",
                        1.0,
                        f"重建完成，Mesh {mesh_faces} 个三角面",
                        num_frames=nf,
                        processing_time_secs=te,
                        num_points=np_pts,
                        artifact_metadata=settings.get("_artifact_metadata"),
                        mesh_stats=mesh_stats,
                    )
                    logger.info(
                        "Job %s completed (point cloud %.1f MB, mesh %.1f MB, %s)",
                        job_id,
                        len(glb_data) / 1024 / 1024,
                        len(mesh_data) / 1024 / 1024,
                        mesh_stats,
                    )

                # Aggressive GPU cleanup between jobs to prevent OOM
                del glb_data
                del mesh_data
                import gc; gc.collect()
                try:
                    import torch as _torch
                    _torch.cuda.empty_cache()
                    _torch.cuda.reset_peak_memory_stats()
                except: pass

            except Exception as e:
                logger.exception(f"Job {job_id} failed")
                try:
                    partial_stats = settings if point_cloud_uploaded else {}
                    _update_status(
                        job_id,
                        "partial" if point_cloud_uploaded else "failed",
                        0.9 if point_cloud_uploaded else 0,
                        str(e)[:500],
                        num_frames=partial_stats.get("_num_frames", 0),
                        num_points=partial_stats.get("_num_points", 0),
                        processing_time_secs=partial_stats.get("_total_elapsed", 0),
                        artifact_metadata=partial_stats.get("_artifact_metadata"),
                        mesh_stats=partial_stats.get("_mesh_stats"),
                    )
                except Exception:
                    pass
                # Also cleanup GPU after failures
                import gc; gc.collect()
                try:
                    import torch as _torch
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except: pass

        time.sleep(POLL_INTERVAL)


def _update_status(job_id: str, status: str, progress: float, detail: str = "",
                   num_frames: int = 0, num_points: int = 0,
                   processing_time_secs: float = 0,
                   artifact_metadata: dict | None = None,
                   mesh_stats: dict | None = None):
    payload = {"status": status, "progress": progress, "detail": detail,
               "error_message": detail if status in ("failed", "partial") else "",
               "num_frames": int(num_frames), "num_points": int(num_points),
               "processing_time_secs": float(processing_time_secs)}
    if artifact_metadata is not None:
        payload["artifact_metadata"] = artifact_metadata
    if mesh_stats is not None:
        payload["mesh_stats"] = mesh_stats
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/gpu/status/{job_id}",
        data=data,
        headers=_worker_headers(**{"Content-Type": "application/json"}),
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _upload_result(job_id: str, glb_data: bytes):
    # Upload as raw binary (not multipart) for reliability with large files
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/result/{job_id}",
                data=glb_data,
                headers=_worker_headers(**{
                    "Content-Type": "application/octet-stream",
                    "X-Artifact-Color-Space": "linear-srgb",
                }),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=300)
            return
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Upload attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                raise

def _upload_mesh(job_id: str, mesh_data: bytes):
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/result_mesh/{job_id}",
                data=mesh_data,
                headers=_worker_headers(**{"Content-Type": "application/octet-stream"}),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=300)
            return
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Mesh upload attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                raise

if __name__ == "__main__":
    poll_and_process()

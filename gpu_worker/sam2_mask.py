from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import numpy as np


class Sam2ConfigurationError(RuntimeError):
    pass


@dataclass
class PackedMaskStore:
    height: int
    width: int
    packed_masks: dict[int, bytes]

    def load(self, frame_indices: Iterable[int], height: int, width: int) -> np.ndarray:
        if (height, width) != (self.height, self.width):
            raise Sam2ConfigurationError(
                f"SAM2 mask shape {(self.height, self.width)} does not match sidecar {(height, width)}"
            )
        result = []
        for frame_index in frame_indices:
            packed = self.packed_masks.get(int(frame_index))
            if packed is None:
                raise Sam2ConfigurationError(f"SAM2 mask missing for source frame {frame_index}")
            result.append(np.unpackbits(np.frombuffer(packed, dtype=np.uint8))[: height * width].reshape(height, width).astype(bool))
        return np.stack(result, axis=0) if result else np.empty((0, height, width), dtype=bool)


def _resize_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    source_height, source_width = mask.shape
    if (source_height, source_width) == (height, width):
        return mask.astype(bool, copy=False)
    import cv2

    source_ratio = source_width / source_height
    target_ratio = width / height
    if abs(source_ratio - target_ratio) > 0.02:
        if source_ratio > target_ratio:
            cropped_width = max(1, round(source_height * target_ratio))
            left = (source_width - cropped_width) // 2
            mask = mask[:, left:left + cropped_width]
        else:
            cropped_height = max(1, round(source_width / target_ratio))
            top = (source_height - cropped_height) // 2
            mask = mask[top:top + cropped_height, :]
    return cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)


def _prompt_operation_sets(prompts: list[Mapping[str, Any]]) -> tuple[set[int], set[int]]:
    keep = {int(p["object_id"]) for p in prompts if p.get("operation") == "keep"}
    exclude = {int(p["object_id"]) for p in prompts if p.get("operation") == "exclude"}
    return keep, exclude


def _add_prompt(predictor: Any, state: dict, prompt: Mapping[str, Any], first_for_object: bool) -> None:
    frame_index = int(prompt["frame_index"])
    object_id = int(prompt["object_id"])
    kind = prompt.get("kind")
    if kind == "point":
        points = np.asarray([[float(prompt["x"]), float(prompt["y"])]], dtype=np.float32)
        labels = np.asarray([int(prompt["label"])], dtype=np.int32)
        predictor.add_new_points_or_box(
            state,
            frame_index,
            object_id,
            points=points,
            labels=labels,
            clear_old_points=first_for_object,
            normalize_coords=True,
        )
        return
    if kind == "box":
        box = np.asarray(
            [float(prompt["x0"]), float(prompt["y0"]), float(prompt["x1"]), float(prompt["y1"])],
            dtype=np.float32,
        )
        predictor.add_new_points_or_box(
            state,
            frame_index,
            object_id,
            box=box,
            clear_old_points=first_for_object,
            normalize_coords=True,
        )
        return
    raise Sam2ConfigurationError(f"Unsupported SAM2 prompt kind: {kind}")


def build_sam2_mask_store(
    video_path: str,
    prompts: list[Mapping[str, Any]],
    requested_frame_indices: Iterable[int],
    output_height: int,
    output_width: int,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> PackedMaskStore:
    if not prompts:
        raise Sam2ConfigurationError("SAM2 requires at least one point or box prompt")
    checkpoint = os.environ.get("SAM2_CHECKPOINT", "").strip()
    model_cfg = os.environ.get("SAM2_MODEL_CFG", "configs/sam2.1/sam2.1_hiera_l.yaml").strip()
    device = os.environ.get("SAM2_DEVICE", "cuda").strip() or "cuda"
    if not checkpoint:
        raise Sam2ConfigurationError("SAM2_CHECKPOINT is not configured on the GPU Worker")
    if not os.path.isfile(checkpoint):
        raise Sam2ConfigurationError("SAM2_CHECKPOINT does not exist on the GPU Worker")
    if not model_cfg:
        raise Sam2ConfigurationError("SAM2_MODEL_CFG is not configured on the GPU Worker")

    try:
        import torch
        from sam2.build_sam import build_sam2_video_predictor
    except ImportError as exc:
        raise Sam2ConfigurationError("SAM2 is not installed on the GPU Worker") from exc

    requested = {int(index) for index in requested_frame_indices}
    if not requested or min(requested) < 0:
        raise Sam2ConfigurationError("SAM2 requested frame indices are invalid")
    if progress_callback:
        progress_callback(0.05, "正在加载 SAM2 预训练模型")
    predictor = build_sam2_video_predictor(model_cfg, checkpoint, device=device)
    state = predictor.init_state(
        video_path,
        offload_video_to_cpu=True,
        offload_state_to_cpu=True,
    )
    object_ids_seen: set[int] = set()
    for prompt in prompts:
        if cancel_check and cancel_check():
            raise RuntimeError("SAM2 reconstruction cancelled")
        object_id = int(prompt["object_id"])
        _add_prompt(predictor, state, prompt, object_id not in object_ids_seen)
        object_ids_seen.add(object_id)

    keep_ids, exclude_ids = _prompt_operation_sets(prompts)
    packed_masks: dict[int, bytes] = {}
    total_frames = int(state.get("num_frames", max(requested) + 1))

    def _consume(processed, frame_index, object_ids, masks, total):
        if frame_index not in requested:
            return
        values = masks.detach().float().cpu().numpy() if isinstance(masks, torch.Tensor) else np.asarray(masks)
        values = np.squeeze(values)
        if values.ndim == 2:
            values = values[None, ...]
        ids = [int(value) for value in object_ids]
        combined_keep = np.zeros(values.shape[-2:], dtype=bool)
        combined_exclude = np.zeros(values.shape[-2:], dtype=bool)
        for index, object_id in enumerate(ids):
            mask = values[index] > 0
            if object_id in keep_ids:
                combined_keep |= mask
            if object_id in exclude_ids:
                combined_exclude |= mask
        selected = (combined_keep if keep_ids else np.ones_like(combined_exclude)) & ~combined_exclude
        selected = _resize_mask(selected, output_height, output_width)
        packed_masks[frame_index] = np.packbits(selected.reshape(-1)).tobytes()
        if progress_callback:
            progress_callback(0.1 + 0.35 * (frame_index + 1) / max(total, 1), "SAM2 正在传播区域")

    for processed, (frame_index, object_ids, masks) in enumerate(predictor.propagate_in_video(state)):
        if cancel_check and cancel_check():
            raise RuntimeError("SAM2 reconstruction cancelled")
        _consume(processed, frame_index, object_ids, masks, total_frames)

    if packed_masks.keys() and min(packed_masks) > 0:
        earliest = min(packed_masks)
        missing_before = {frame_index for frame_index in requested if frame_index < earliest}
        if missing_before:
            for _, (frame_index, object_ids, masks) in enumerate(predictor.propagate_in_video(state, reverse=True)):
                if cancel_check and cancel_check():
                    raise RuntimeError("SAM2 reconstruction cancelled")
                _consume(0, frame_index, object_ids, masks, total_frames)

    missing = requested - packed_masks.keys()
    if missing:
        raise Sam2ConfigurationError(f"SAM2 did not produce masks for frames: {sorted(missing)[:8]}")
    return PackedMaskStore(output_height, output_width, packed_masks)

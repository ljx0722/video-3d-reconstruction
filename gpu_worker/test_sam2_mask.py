import importlib.util
import os
import unittest
from unittest import mock

import numpy as np

from gpu_worker.sam2_mask import (
    PackedMaskStore,
    Sam2ConfigurationError,
    _prompt_operation_sets,
    _resize_mask,
    build_sam2_mask_store,
)


class PackedMaskStoreTests(unittest.TestCase):
    def test_round_trips_packed_masks(self):
        store = PackedMaskStore(2, 4, {
            0: np.packbits(np.array([1, 1, 0, 0, 0, 0, 1, 1], dtype=np.uint8)).tobytes(),
            1: np.packbits(np.zeros(8, dtype=np.uint8)).tobytes(),
        })
        masks = store.load([0, 1], 2, 4)
        self.assertEqual(masks.shape, (2, 2, 4))
        np.testing.assert_array_equal(masks[0], [[True, True, False, False], [False, False, True, True]])
        np.testing.assert_array_equal(masks[1], np.zeros((2, 4), dtype=bool))

    def test_raises_on_missing_frame(self):
        store = PackedMaskStore(2, 2, {0: np.packbits(np.ones(4, dtype=np.uint8)).tobytes()})
        with self.assertRaises(Sam2ConfigurationError):
            store.load([0, 1], 2, 2)

    def test_raises_on_shape_mismatch(self):
        store = PackedMaskStore(2, 2, {})
        with self.assertRaises(Sam2ConfigurationError):
            store.load([], 3, 3)

    def test_resize_preserves_identity(self):
        mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(_resize_mask(mask, 2, 2).astype(np.uint8), mask)

    def test_prompt_operation_sets(self):
        keep, exclude = _prompt_operation_sets([
            {"object_id": 1, "operation": "keep"},
            {"object_id": 2, "operation": "exclude"},
            {"object_id": 3, "operation": "keep"},
        ])
        self.assertEqual(keep, {1, 3})
        self.assertEqual(exclude, {2})

    def test_fails_explicitly_when_checkpoint_unset(self):
        prompt = [{"kind": "point", "frame_index": 0, "x": 1, "y": 1, "label": 1, "object_id": 1, "operation": "keep"}]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SAM2_CHECKPOINT", None)
            with self.assertRaisesRegex(Sam2ConfigurationError, "SAM2_CHECKPOINT"):
                build_sam2_mask_store("video.mp4", prompt, [0], 2, 2)

    def test_fails_explicitly_when_prompts_empty(self):
        with mock.patch.dict(os.environ, {"SAM2_CHECKPOINT": "/nonexistent.pt"}, clear=False):
            with self.assertRaisesRegex(Sam2ConfigurationError, "at least one"):
                build_sam2_mask_store("video.mp4", [], [0], 2, 2)

    def test_fails_explicitly_when_checkpoint_missing_on_disk(self):
        with mock.patch.dict(os.environ, {"SAM2_CHECKPOINT": "/nonexistent.pt"}, clear=False):
            with self.assertRaisesRegex(Sam2ConfigurationError, "does not exist"):
                build_sam2_mask_store(
                    "video.mp4",
                    [{"kind": "point", "frame_index": 0, "x": 1, "y": 1, "label": 1, "object_id": 1, "operation": "keep"}],
                    [0], 2, 2,
                )


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.api.gpu import _merge_status_settings, _validate_glb, _write_atomic
from app.api.jobs import _job_to_response


def make_glb(payload: bytes = b"{}  ") -> bytes:
    json_chunk = payload + b" " * ((4 - len(payload) % 4) % 4)
    total_length = 12 + 8 + len(json_chunk)
    return (
        b"glTF"
        + (2).to_bytes(4, "little")
        + total_length.to_bytes(4, "little")
        + len(json_chunk).to_bytes(4, "little")
        + b"JSON"
        + json_chunk
    )


class GpuUploadValidationTests(unittest.TestCase):
    def test_accepts_well_formed_glb_header(self):
        _validate_glb(make_glb(), "Mesh")

    def test_rejects_empty_body(self):
        with self.assertRaises(HTTPException) as caught:
            _validate_glb(b"", "Mesh")
        self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_declared_length_mismatch(self):
        invalid = bytearray(make_glb())
        invalid[8:12] = (999).to_bytes(4, "little")
        with self.assertRaisesRegex(HTTPException, "length"):
            _validate_glb(bytes(invalid), "Mesh")

    def test_atomic_write_replaces_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "result_mesh.glb")
            _write_atomic(path, b"first")
            _write_atomic(path, b"second")
            with open(path, "rb") as result_file:
                self.assertEqual(result_file.read(), b"second")
            self.assertEqual(os.listdir(tmpdir), ["result_mesh.glb"])

    def test_reports_point_cloud_artifact_while_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "app.api.jobs.storage_service.settings.upload_dir", tmpdir
        ):
            job_id = "job-1"
            job_dir = os.path.join(tmpdir, job_id)
            os.makedirs(job_dir)
            _write_atomic(os.path.join(job_dir, "result.glb"), make_glb())
            job = SimpleNamespace(
                id=job_id,
                status="processing",
                progress=0.9,
                settings="{}",
                result_path=None,
                error_message=None,
                num_frames=1,
                num_points=10,
                processing_time_secs=1.0,
                created_at=None,
                updated_at=None,
            )

            response = _job_to_response(job)

        self.assertEqual(response["status"], "processing")
        self.assertTrue(response["point_cloud_available"])
        self.assertFalse(response["mesh_available"])

    def test_status_metadata_persists_under_internal_settings_keys(self):
        settings = json.loads(_merge_status_settings(
            '{"fps": 10, "file_name": "input.mp4"}',
            "completed",
            {
                "detail": "重建完成",
                "artifact_metadata": {"version": 2, "alignment": "world"},
                "mesh_stats": {"mesh_triangles": 321},
            },
        ))

        self.assertEqual(settings["fps"], 10)
        self.assertEqual(settings["file_name"], "input.mp4")
        self.assertEqual(
            settings["_artifact_metadata"],
            {"version": 2, "alignment": "world"},
        )
        self.assertEqual(settings["_mesh_stats"], {"mesh_triangles": 321})

    def test_completed_status_clears_stale_mesh_state(self):
        settings = json.loads(_merge_status_settings(
            json.dumps({
                "fps": 10,
                "_mesh_error": "old failure",
                "_mesh_stats": {"mesh_triangles": 12},
                "_artifact_metadata": {"version": 1},
            }),
            "completed",
            {"detail": "重建完成"},
        ))

        self.assertNotIn("_mesh_error", settings)
        self.assertNotIn("_mesh_stats", settings)
        self.assertEqual(settings["_artifact_metadata"], {"version": 1})

    def test_partial_status_preserves_artifact_metadata_and_updates_mesh_state(self):
        settings = json.loads(_merge_status_settings(
            json.dumps({
                "fps": 10,
                "_artifact_metadata": {"version": 1},
                "_mesh_stats": {"mesh_triangles": 12},
            }),
            "partial",
            {
                "detail": "Mesh 生成失败: no surface",
                "mesh_stats": {"alignment_applied": False},
            },
        ))

        self.assertEqual(settings["_artifact_metadata"], {"version": 1})
        self.assertEqual(settings["_mesh_stats"], {"alignment_applied": False})
        self.assertEqual(settings["_mesh_error"], "no surface")

    def test_partial_status_clears_stale_mesh_stats_when_payload_omits_them(self):
        settings = json.loads(_merge_status_settings(
            json.dumps({
                "_artifact_metadata": {"version": 1},
                "_mesh_stats": {"mesh_triangles": 12},
            }),
            "partial",
            {"detail": "Mesh 生成失败: no surface"},
        ))

        self.assertEqual(settings["_artifact_metadata"], {"version": 1})
        self.assertNotIn("_mesh_stats", settings)

    def test_job_response_exposes_persisted_metadata(self):
        job = SimpleNamespace(
            id="job-metadata",
            status="completed",
            progress=1.0,
            settings=json.dumps({
                "fps": 10,
                "_artifact_metadata": {"version": 2},
                "_mesh_stats": {"mesh_triangles": 321},
            }),
            result_path=None,
            error_message=None,
            num_frames=1,
            num_points=10,
            processing_time_secs=1.0,
            created_at=None,
            updated_at=None,
        )

        response = _job_to_response(job)

        self.assertEqual(response["artifact_metadata"], {"version": 2})
        self.assertEqual(response["mesh_stats"], {"mesh_triangles": 321})

    def test_legacy_job_response_returns_null_metadata(self):
        job = SimpleNamespace(
            id="legacy-job",
            status="completed",
            progress=1.0,
            settings='{"fps": 10}',
            result_path=None,
            error_message=None,
            num_frames=1,
            num_points=10,
            processing_time_secs=1.0,
            created_at=None,
            updated_at=None,
        )

        response = _job_to_response(job)

        self.assertIsNone(response["artifact_metadata"])
        self.assertIsNone(response["mesh_stats"])

    def test_legacy_invalid_settings_accept_status_metadata(self):
        settings = json.loads(_merge_status_settings(
            "not-json",
            "completed",
            {
                "artifact_metadata": {"version": 2},
                "mesh_stats": {"mesh_triangles": 321},
            },
        ))

        self.assertEqual(settings["_artifact_metadata"], {"version": 2})
        self.assertEqual(settings["_mesh_stats"], {"mesh_triangles": 321})


if __name__ == "__main__":
    unittest.main()

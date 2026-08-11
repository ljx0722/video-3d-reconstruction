import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.api.gpu import _validate_glb, _write_atomic
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


if __name__ == "__main__":
    unittest.main()

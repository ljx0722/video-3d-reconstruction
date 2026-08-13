import hashlib
import io
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


class MeshRunApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls.tempdir.name)
        cls.database_path = cls.root / "jobs.db"
        cls.upload_dir = cls.root / "uploads"
        cls.upload_dir.mkdir()
        cls.job_id = "11111111-1111-1111-1111-111111111111"
        job_dir = cls.upload_dir / cls.job_id
        job_dir.mkdir()
        cls.valid_glb = struct.pack("<4sII", b"glTF", 2, 20) + b"\0" * 8
        (job_dir / "result.glb").write_bytes(cls.valid_glb)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.secret = "mesh-run-test-secret"
        backend_dir = Path(__file__).resolve().parent
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": f"sqlite+aiosqlite:///{cls.database_path.as_posix()}",
            "UPLOAD_DIR": str(cls.upload_dir),
            "GPU_SECRET": cls.secret,
            "PYTHONPATH": str(backend_dir),
        })
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(cls.port), "--log-level", "warning"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{cls.base_url}/api/v1/health", timeout=1):
                    break
            except Exception:
                if cls.server.poll() is not None:
                    output = cls.server.stdout.read() if cls.server.stdout else ""
                    raise RuntimeError(f"Test server exited early: {output}")
                time.sleep(0.1)
        else:
            raise RuntimeError("Timed out waiting for test server")

        now = datetime.utcnow().isoformat(" ")
        with sqlite3.connect(cls.database_path) as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, session_id, status, video_path, settings, result_path,
                    error_message, progress, num_frames, num_points,
                    processing_time_secs, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cls.job_id,
                    "anonymous",
                    "completed",
                    cls.job_id,
                    json.dumps({"_artifact_metadata": {"color_space": "linear-srgb"}}),
                    "results/pointcloud.glb",
                    None,
                    1.0,
                    1,
                    2,
                    1.0,
                    now,
                    now,
                ),
            )
            connection.commit()

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        if cls.server.stdout:
            cls.server.stdout.close()
        cls.tempdir.cleanup()

    @classmethod
    def request(cls, path, *, method="GET", data=None, gpu=False, lease=None):
        headers = {}
        body = data
        if isinstance(data, dict):
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        if gpu:
            headers["Authorization"] = f"Bearer {cls.secret}"
        if lease:
            headers["X-Mesh-Lease-Token"] = lease
        request = urllib.request.Request(
            f"{cls.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
            content = response.read()
            payload = json.loads(content) if content else None
            return response.status, dict(response.headers), payload
        except urllib.error.HTTPError as exc:
            content = exc.read()
            payload = json.loads(content) if content else None
            return exc.code, dict(exc.headers), payload

    def test_full_mesh_run_lifecycle_and_immutable_file(self):
        create_path = f"/api/v1/jobs/{self.job_id}/mesh-runs"
        status, _, created = self.request(
            create_path,
            method="POST",
            data={"preset": "quick", "config": {}},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["source_color_space"], "linear-srgb")
        run_id = created["id"]

        status, _, cached = self.request(
            create_path,
            method="POST",
            data={"preset": "quick", "config": {}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(cached["id"], run_id)

        status, _, claimed = self.request(
            "/api/v1/gpu/mesh-runs/claim",
            method="POST",
            data={"worker_id": "worker-test"},
            gpu=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(claimed["id"], run_id)
        lease = claimed["lease_token"]

        status, _, heartbeat = self.request(
            f"/api/v1/gpu/mesh-runs/{run_id}/heartbeat",
            method="POST",
            data={},
            gpu=True,
            lease=lease,
        )
        self.assertEqual(status, 200)
        self.assertFalse(heartbeat["cancel_requested"])

        status, _, _ = self.request(
            f"/api/v1/gpu/mesh-runs/{run_id}/status",
            method="POST",
            data={"status": "processing", "progress": 0.5},
            gpu=True,
            lease="stale-token",
        )
        self.assertEqual(status, 409)

        status, _, _ = self.request(
            f"/api/v1/gpu/mesh-runs/{run_id}/result",
            method="POST",
            data=self.valid_glb,
            gpu=True,
            lease=lease,
        )
        self.assertEqual(status, 200)

        status, _, job = self.request(f"/api/v1/jobs/{self.job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job["active_mesh_run_id"], run_id)
        self.assertIn(f"/mesh-runs/{run_id}/result.glb", job["mesh_url"])

        status, headers, _ = self.request(job["mesh_url"], method="HEAD")
        self.assertEqual(status, 200)
        cache_control = next(
            value for key, value in headers.items() if key.lower() == "cache-control"
        )
        self.assertIn("immutable", cache_control)
        etag = next((value for key, value in headers.items() if key.lower() == "etag"), None)
        self.assertTrue(etag)

        status, _, selected = self.request(
            f"/api/v1/jobs/{self.job_id}/active-mesh",
            method="PATCH",
            data={"run_id": None},
        )
        self.assertEqual(status, 200)
        self.assertIsNone(selected["active_mesh_run_id"])

        status, _, _ = self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs/{run_id}", method="DELETE"
        )
        self.assertEqual(status, 204)

    def test_sidecar_upload_enables_balanced_mesh_run(self):
        chunk = io.BytesIO()
        np = __import__("numpy")
        np.savez_compressed(
            chunk,
            depth=np.ones((1, 2, 2), dtype=np.float16),
            confidence=np.ones((1, 2, 2), dtype=np.float16),
            intrinsic=np.broadcast_to(np.eye(3, dtype=np.float32), (1, 3, 3)),
            c2w=np.broadcast_to(np.eye(4, dtype=np.float32), (1, 4, 4)),
            frame_indices=np.array([0], dtype=np.int32),
        )
        data = chunk.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        begin = {
            "version": "mesh-source-v1",
            "frame_count": 1,
            "chunk_count": 1,
            "image_height": 2,
            "image_width": 2,
            "coordinate_system": "lingbot-c2w-opencv",
            "color_space": "srgb",
            "alignment": "first-camera-opengl-y180",
            "source_model": "test",
            "source_fps": 30.0,
            "source_frame_count": 90,
            "source_height": 2,
            "source_width": 2,
        }
        status, _, _ = self.request(
            f"/api/v1/gpu/mesh-sources/{self.job_id}/begin",
            method="POST", data=begin, gpu=True,
        )
        self.assertEqual(status, 200)
        status, _, _ = self.request(
            f"/api/v1/gpu/mesh-sources/{self.job_id}/chunks/chunk-0000.npz?sha256={digest}&size_bytes={len(data)}",
            method="PUT", data=data, gpu=True,
        )
        self.assertEqual(status, 200)
        manifest = {
            **begin,
            "scene_diagonal": 1.0,
            "alignment_matrix": np.eye(4).tolist(),
            "chunks": [{
                "name": "chunk-0000.npz", "sha256": digest, "size_bytes": len(data),
                "frame_start": 0, "frame_stop": 1,
            }],
        }
        status, _, completed = self.request(
            f"/api/v1/gpu/mesh-sources/{self.job_id}/complete",
            method="POST", data={"manifest": manifest}, gpu=True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(completed["manifest_sha256"])

        status, _, created = self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs",
            method="POST", data={"preset": "balanced", "config": {}},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["source_kind"], "mesh-source-v1")
        self.assertEqual(created["algorithm"], "tsdf")
        self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs/{created['id']}/cancel",
            method="POST", data={},
        )
        self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs/{created['id']}", method="DELETE"
        )

        status, _, _ = self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs",
            method="POST",
            data={"preset": "high-quality", "config": {
                "sam2_prompts": [{"kind": "point", "frame_index": 5, "x": 1, "y": 1, "object_id": 1}],
            }},
        )
        self.assertEqual(status, 201)

        status, _, _ = self.request(
            f"/api/v1/jobs/{self.job_id}/mesh-runs",
            method="POST",
            data={"preset": "high-quality", "config": {
                "sam2_prompts": [{"kind": "point", "frame_index": 999, "x": 1, "y": 1, "object_id": 1}],
            }},
        )
        self.assertEqual(status, 422)

    def test_queued_run_can_be_cancelled_and_deleted(self):
        create_path = f"/api/v1/jobs/{self.job_id}/mesh-runs"
        status, _, created = self.request(
            create_path,
            method="POST",
            data={"preset": "detail", "config": {}},
        )
        self.assertEqual(status, 201)
        run_id = created["id"]
        status, _, cancelled = self.request(
            f"{create_path}/{run_id}/cancel", method="POST", data={}
        )
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["status"], "cancelled")
        status, _, _ = self.request(f"{create_path}/{run_id}", method="DELETE")
        self.assertEqual(status, 204)

    def test_rejects_excess_pending_mesh_runs(self):
        create_path = f"/api/v1/jobs/{self.job_id}/mesh-runs"
        run_ids = []
        for index in range(3):
            status, _, created = self.request(
                create_path,
                method="POST",
                data={"preset": "quick", "config": {"target_triangles": 100_000 + index}},
            )
            self.assertEqual(status, 201)
            run_ids.append(created["id"])
        status, _, rejected = self.request(
            create_path,
            method="POST",
            data={"preset": "quick", "config": {"target_triangles": 400_000}},
        )
        self.assertEqual(status, 422)
        for run_id in run_ids:
            self.request(f"{create_path}/{run_id}/cancel", method="POST", data={})
            self.request(f"{create_path}/{run_id}", method="DELETE")


if __name__ == "__main__":
    unittest.main()

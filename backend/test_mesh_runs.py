import hashlib
import json
import os
import tempfile
import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, Job, MeshRun
from app.schemas.mesh_run import MeshRunCreate, MeshRunConfig
from app.services.mesh_run_service import canonical_config, hash_lease_token


class MeshRunConfigTests(unittest.TestCase):
    def test_presets_produce_valid_effective_configs(self):
        for preset in ("quick", "detail", "open-boundary"):
            request = MeshRunCreate(preset=preset)
            config = request.effective_config()
            self.assertIsInstance(config, MeshRunConfig)
            self.assertGreaterEqual(config.target_triangles, 50_000)
            self.assertLessEqual(config.target_triangles, 500_000)

    def test_rejects_unsorted_bpa_radii(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MeshRunConfig(bpa_radius_multipliers=(3, 2, 6))

    def test_canonical_config_is_stable_and_compact(self):
        config = MeshRunConfig(poisson_depth=8, target_triangles=300_000)
        first = canonical_config(config)
        second = canonical_config(MeshRunConfig.model_validate(json.loads(first)))
        self.assertEqual(first, second)
        self.assertNotIn(" ", first)

    def test_high_quality_preset_enables_sam2_only_with_prompts(self):
        request = MeshRunCreate(
            preset="high-quality",
            config={"sam2_prompts": [{"kind": "point", "frame_index": 3, "x": 10, "y": 20, "object_id": 1}]},
        )
        config = request.effective_config()
        self.assertTrue(config.use_sam2)
        self.assertEqual(config.algorithm, "tsdf")
        self.assertEqual(len(config.sam2_prompts), 1)

    def test_sam2_prompts_require_use_sam2(self):
        with self.assertRaisesRegex(ValueError, "use_sam2"):
            MeshRunConfig(sam2_prompts=[{"kind": "point", "frame_index": 0, "x": 1, "y": 1, "object_id": 1}])

    def test_sam2_rejects_mixed_object_operations(self):
        with self.assertRaisesRegex(ValueError, "same operation"):
            MeshRunConfig(
                algorithm="tsdf",
                use_sam2=True,
                sam2_prompts=[
                    {"kind": "point", "frame_index": 0, "x": 1, "y": 1, "object_id": 1, "operation": "keep"},
                    {"kind": "box", "frame_index": 1, "x0": 0, "y0": 0, "x1": 2, "y1": 2, "object_id": 1, "operation": "exclude"},
                ],
            )

    def test_sam2_rejects_inverted_box(self):
        with self.assertRaisesRegex(ValueError, "x0 < x1"):
            MeshRunConfig(
                algorithm="tsdf",
                use_sam2=True,
                sam2_prompts=[{"kind": "box", "frame_index": 0, "x0": 5, "y0": 1, "x1": 2, "y1": 3, "object_id": 1}],
            )

    def test_lease_hash_does_not_reveal_token(self):
        token = "secret-lease-token"
        digest = hash_lease_token(token)
        self.assertEqual(digest, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, digest)


class MeshRunSchemaUpgradeTests(unittest.TestCase):
    def test_create_all_adds_mesh_runs_without_losing_existing_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = os.path.join(tmpdir, "jobs.db")
            engine = create_engine(f"sqlite:///{database_path}")
            Job.__table__.create(engine)
            with Session(engine) as session:
                session.add(Job(id="11111111-1111-1111-1111-111111111111", status="completed"))
                session.commit()

            Base.metadata.create_all(engine)
            self.assertIn("mesh_runs", inspect(engine).get_table_names())
            with Session(engine) as session:
                job = session.get(Job, "11111111-1111-1111-1111-111111111111")
                self.assertIsNotNone(job)
                session.add(MeshRun(
                    id="22222222-2222-2222-2222-222222222222",
                    job_id=job.id,
                    preset="quick",
                    algorithm="auto",
                    config_json="{}",
                    config_hash="a" * 64,
                    cache_key="b" * 64,
                    cache_slot="b" * 64,
                    source_path=os.path.join(job.id, "result.glb"),
                    source_sha256="c" * 64,
                ))
                session.commit()
                self.assertEqual(session.query(MeshRun).count(), 1)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

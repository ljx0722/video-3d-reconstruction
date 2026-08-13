from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MeshAlgorithm = Literal["auto", "poisson", "bpa", "tsdf"]
MeshPreset = Literal["quick", "detail", "open-boundary", "balanced", "high-quality"]


class Sam2PointPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["point"] = "point"
    frame_index: int = Field(ge=0)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    label: Literal[0, 1] = 1
    object_id: int = Field(ge=0, le=127)
    operation: Literal["keep", "exclude"] = "keep"


class Sam2BoxPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["box"] = "box"
    frame_index: int = Field(ge=0)
    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    object_id: int = Field(ge=0, le=127)
    operation: Literal["keep", "exclude"] = "keep"

    @model_validator(mode="after")
    def validate_box(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("box must satisfy x0 < x1 and y0 < y1")
        return self


Sam2Prompt = Annotated[
    Sam2PointPrompt | Sam2BoxPrompt,
    Field(discriminator="kind"),
]


class MeshRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: MeshAlgorithm = "auto"
    voxel_size_ratio: float = Field(default=0.0025, ge=0.0005, le=0.01)
    outlier_nb_neighbors: int = Field(default=30, ge=10, le=50)
    outlier_std_ratio: float = Field(default=2.0, ge=1.0, le=3.0)
    normal_radius_multiplier: float = Field(default=3.0, ge=2.0, le=8.0)
    normal_max_nn: int = Field(default=30, ge=20, le=100)
    normal_orientation_k: int = Field(default=30, ge=10, le=100)
    poisson_depth: int = Field(default=7, ge=6, le=9)
    poisson_scale: float = Field(default=1.05, ge=1.01, le=1.2)
    density_quantile: float = Field(default=0.05, ge=0.0, le=0.15)
    bpa_radius_multipliers: tuple[float, float, float] = (1.5, 3.0, 6.0)
    component_min_triangles: int = Field(default=500, ge=50, le=2000)
    component_min_area_ratio: float = Field(default=0.01, ge=0.0, le=0.05)
    target_triangles: int = Field(default=150_000, ge=50_000, le=500_000)
    color_neighbors: int = Field(default=4, ge=1, le=16)
    tsdf_voxel_size_ratio: float = Field(default=0.0025, ge=0.001, le=0.005)
    tsdf_truncation_multiplier: float = Field(default=4.0, ge=3.0, le=8.0)
    confidence_percentile: float = Field(default=10.0, ge=0.0, le=30.0)
    depth_min: float = Field(default=0.05, ge=0.001, le=100.0)
    depth_max: float = Field(default=100.0, ge=0.1, le=1000.0)
    frame_stride: int = Field(default=1, ge=1, le=5)
    min_tsdf_weight: float = Field(default=1.0, ge=0.0, le=20.0)
    tsdf_block_count: int = Field(default=20_000, ge=1_000, le=100_000)
    use_sam2: bool = False
    sam2_prompts: list[Sam2Prompt] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_bpa_radii(self):
        if self.depth_min >= self.depth_max:
            raise ValueError("depth_min must be smaller than depth_max")
        if any(value < 1 or value > 8 for value in self.bpa_radius_multipliers):
            raise ValueError("BPA radius multipliers must be between 1 and 8")
        if not (
            self.bpa_radius_multipliers[0]
            < self.bpa_radius_multipliers[1]
            < self.bpa_radius_multipliers[2]
        ):
            raise ValueError("BPA radius multipliers must be strictly increasing")
        if self.use_sam2:
            if self.algorithm != "tsdf":
                raise ValueError("SAM2 filtering requires TSDF")
            if not self.sam2_prompts:
                raise ValueError("SAM2 filtering requires at least one prompt")
            operations_by_object: dict[int, str] = {}
            for prompt in self.sam2_prompts:
                operation = operations_by_object.setdefault(prompt.object_id, prompt.operation)
                if operation != prompt.operation:
                    raise ValueError("all prompts for one SAM2 object must use the same operation")
        elif self.sam2_prompts:
            raise ValueError("sam2_prompts require use_sam2=true")
        return self


MESH_PRESETS: dict[MeshPreset, MeshRunConfig] = {
    "quick": MeshRunConfig(
        algorithm="auto", voxel_size_ratio=0.004, poisson_depth=7, target_triangles=100_000
    ),
    "detail": MeshRunConfig(
        algorithm="auto", voxel_size_ratio=0.0015, poisson_depth=8, target_triangles=300_000
    ),
    "open-boundary": MeshRunConfig(
        algorithm="bpa", voxel_size_ratio=0.0015, target_triangles=300_000
    ),
    "balanced": MeshRunConfig(
        algorithm="tsdf", tsdf_voxel_size_ratio=0.0025, target_triangles=300_000
    ),
    "high-quality": MeshRunConfig(
        algorithm="tsdf",
        tsdf_voxel_size_ratio=0.0015,
        tsdf_truncation_multiplier=6.0,
        frame_stride=1,
        target_triangles=500_000,
    ),
}


class MeshRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: MeshPreset = "quick"
    config: dict = Field(default_factory=dict)

    def effective_config(self) -> MeshRunConfig:
        base = MESH_PRESETS[self.preset].model_dump()
        base.update(self.config)
        if self.preset == "high-quality":
            base["use_sam2"] = True
        return MeshRunConfig.model_validate(base)


class ActiveMeshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None


class MeshRunClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=128)


class MeshRunStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress: float | None = Field(default=None, ge=0, le=0.99)
    detail: str | None = Field(default=None, max_length=1000)
    stats: dict | None = None
    status: Literal["processing", "failed", "cancelled"] = "processing"
    error_message: str | None = Field(default=None, max_length=2000)

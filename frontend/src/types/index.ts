export interface ArtifactMetadata {
  version?: number | string;
  alignment?: string;
  color_space?: string;
  confidence_percentile?: number;
  spatial_stride?: number;
  keyframes?: number;
  [key: string]: unknown;
}

export interface MeshStats {
  mesh_triangles?: number;
  mesh_vertices?: number;
  alignment_applied?: boolean | number;
  glb_bytes?: number;
  entity_qualified?: boolean;
  surface_type?: 'entity' | 'surface';
  watertight?: boolean;
  winding_consistent?: boolean;
  connected_components?: number;
  boundary_edges?: number;
  non_manifold_edges?: number;
  degenerate_faces?: number;
  valid_normal_ratio?: number;
  self_intersecting?: boolean | null;
  bbox_ratio?: number;
  point_to_surface_p50?: number;
  point_to_surface_p95?: number;
  coverage?: number;
  [key: string]: unknown;
}

export interface Sam2PointPrompt {
  kind: 'point';
  frame_index: number;
  x: number;
  y: number;
  label: 0 | 1;
  object_id: number;
  operation: 'keep' | 'exclude';
}

export interface Sam2BoxPrompt {
  kind: 'box';
  frame_index: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  object_id: number;
  operation: 'keep' | 'exclude';
}

export type Sam2Prompt = Sam2PointPrompt | Sam2BoxPrompt;

export interface MeshRunConfig {
  algorithm: 'auto' | 'poisson' | 'bpa' | 'tsdf';
  voxel_size_ratio: number;
  outlier_nb_neighbors: number;
  outlier_std_ratio: number;
  normal_radius_multiplier: number;
  normal_max_nn: number;
  normal_orientation_k: number;
  poisson_depth: number;
  poisson_scale: number;
  density_quantile: number;
  bpa_radius_multipliers: [number, number, number];
  component_min_triangles: number;
  component_min_area_ratio: number;
  target_triangles: number;
  color_neighbors: number;
  tsdf_voxel_size_ratio: number;
  tsdf_truncation_multiplier: number;
  confidence_percentile: number;
  depth_min: number;
  depth_max: number;
  frame_stride: number;
  min_tsdf_weight: number;
  tsdf_block_count: number;
  use_sam2?: boolean;
  sam2_prompts?: Sam2Prompt[];
}

export type MeshRunStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type MeshRunPreset = 'quick' | 'detail' | 'open-boundary' | 'balanced' | 'high-quality';

export interface MeshRun {
  id: string;
  job_id: string;
  preset: MeshRunPreset;
  algorithm: MeshRunConfig['algorithm'];
  status: MeshRunStatus;
  progress: number;
  config: MeshRunConfig;
  cache_key: string;
  source_kind: string;
  source_color_space: string;
  detail: string;
  stats: MeshStats | null;
  error_message: string | null;
  output_url: string | null;
  output_sha256: string | null;
  output_size_bytes: number | null;
  is_active: boolean;
  cancel_requested: boolean;
  attempts: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  cache_hit?: boolean;
}

export interface JobSettings {
  fps: number;
  mode: 'streaming' | 'windowed';
  conf_threshold: number;
}

export interface Job {
  id: string;
  status: 'uploaded' | 'queued' | 'processing' | 'partial' | 'completed' | 'failed';
  progress: number;
  settings: JobSettings;
  result_url: string | null;
  point_cloud_available?: boolean;
  mesh_available?: boolean;
  mesh_url?: string | null;
  active_mesh_run_id?: string | null;
  mesh_source_available?: boolean;
  video_metadata?: {
    source_fps: number;
    source_frame_count: number;
    source_width: number;
    source_height: number;
  } | null;
  mesh_error?: string | null;
  artifact_metadata?: ArtifactMetadata | null;
  mesh_stats?: MeshStats | null;
  error_message: string | null;
  num_frames: number | null;
  num_points: number | null;
  processing_time_secs: number | null;
  created_at: string;
  updated_at: string;
  file_name?: string;
  file_size_bytes?: number;
}

export interface JobCreateResponse {
  id: string;
  status: string;
}

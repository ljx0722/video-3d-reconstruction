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
  mesh_error?: string | null;
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
